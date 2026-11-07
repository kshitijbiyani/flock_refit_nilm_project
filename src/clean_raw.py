import argparse
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import re
from common import load_config, resolve_path, save_table


def inspect_header(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f))


def parse_time(series):
    """Parse REFIT's local wall-clock timestamps; do not pretend they are UTC."""
    return pd.to_datetime(series, format="%Y-%m-%d %H:%M:%S", errors="coerce")


def get_power_columns(header):
    cols = [
        c for c in header
        if c == "Aggregate" or c.startswith("Appliance")
    ]
    if "Aggregate" not in cols:
        raise ValueError("House 1 CSV must contain an Aggregate column.")
    return cols


def find_max_timestamp(path, chunksize=250_000):
    """Find the maximum valid local timestamp without assuming row order."""
    maximum = pd.NaT
    for chunk in pd.read_csv(
        path, usecols=["Time"], chunksize=chunksize,
        encoding="utf-8-sig", low_memory=False
    ):
        times = parse_time(chunk["Time"])
        if times.notna().any():
            chunk_max = times.max()
            maximum = chunk_max if pd.isna(maximum) else max(maximum, chunk_max)
    return maximum


def process_source(path, source_name, power_cols, accumulators, counters,
                   keep_after=None, chunksize=250_000):
    """
    Stream one source file. Timestamp order is deliberately not assumed.
    Duplicate timestamps are collapsed channel-by-channel. If a channel has
    conflicting values at the same timestamp, that channel/timestamp is
    marked missing rather than selecting an arbitrary reading.
    """
    usecols = ["Time"] + power_cols

    for chunk in pd.read_csv(
        path, usecols=usecols, chunksize=chunksize,
        encoding="utf-8-sig", low_memory=False
    ):
        counters["source_rows"] += len(chunk)
        chunk["_time"] = parse_time(chunk["Time"])
        counters["invalid_timestamps"] += int(chunk["_time"].isna().sum())
        chunk = chunk.loc[chunk["_time"].notna()].copy()

        if keep_after is not None:
            chunk = chunk.loc[chunk["_time"] > keep_after].copy()

        if chunk.empty:
            continue

        for col in power_cols:
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce")

        # Count backward steps in the original file order for diagnostics.
        original_times = chunk["_time"]
        backwards = int((original_times.diff() < pd.Timedelta(0)).sum())
        counters[f"{source_name}_backward_steps"] += backwards

        # Collapse duplicate timestamps. Conflicting values are set to NaN
        # for that channel/time; non-conflicting channels remain usable.
        grouped = chunk.groupby("_time", sort=False)
        duplicate_sizes = grouped.size()
        counters[f"{source_name}_duplicate_rows"] += int(
            (duplicate_sizes - 1).clip(lower=0).sum()
        )

        collapsed = grouped[power_cols].median()
        for col in power_cols:
            distinct = grouped[col].nunique(dropna=True)
            conflict_times = distinct.index[distinct > 1]
            if len(conflict_times):
                counters[f"{source_name}_{col}_conflict_timestamps"] += len(conflict_times)
                collapsed.loc[conflict_times, col] = np.nan

        # Aggregate timestamp-level observations into local one-minute bins.
        collapsed.index = pd.DatetimeIndex(collapsed.index).floor("min")
        minute_sum = collapsed.groupby(level=0).sum(min_count=1)
        minute_count = collapsed.groupby(level=0).count()

        for timestamp in minute_sum.index:
            if timestamp not in accumulators:
                accumulators[timestamp] = {
                    "sum": np.zeros(len(power_cols), dtype=float),
                    "count": np.zeros(len(power_cols), dtype=np.int64),
                }
            entry = accumulators[timestamp]
            for i, col in enumerate(power_cols):
                value_count = int(minute_count.loc[timestamp, col])
                if value_count:
                    entry["sum"][i] += float(minute_sum.loc[timestamp, col])
                    entry["count"][i] += value_count


def clean_house1(paths, cfg):
    if not paths:
        raise FileNotFoundError("No raw House 1 CSV files were found.")

    paths = sorted(paths, key=lambda p: p.name.lower())
    header = inspect_header(paths[0])
    if "Time" not in header:
        raise ValueError("House 1 CSV must contain a Time column.")
    power_cols = get_power_columns(header)

    for path in paths:
        if inspect_header(path) != header:
            raise ValueError(f"Column mismatch in {path.name}")

    counters = defaultdict(int)
    accumulators = {}

    # For the two known House 1 parts, Part 1 is retained during their
    # overlap. Part 2 contributes only after Part 1's final timestamp.
    part1 = next((p for p in paths if "part1" in p.name.lower()), None)
    part2 = next((p for p in paths if "part2" in p.name.lower()), None)

    if part1 and part2:
        part1_end = find_max_timestamp(part1)
        if pd.isna(part1_end):
            raise ValueError("Could not find a valid timestamp in House 1 Part 1.")
        process_source(part1, "part1", power_cols, accumulators, counters)
        process_source(
            part2, "part2", power_cols, accumulators, counters,
            keep_after=part1_end
        )
        source_description = (
            f"{part1.name} (including overlap); "
            f"{part2.name} only after {part1_end}"
        )
        overlap_policy = (
            "Part 1 retained during the overlap; Part 2 used only after "
            "the maximum valid Part 1 timestamp. This is a coverage-based "
            "selection policy, not evidence that Part 1 is more accurate."
        )
    else:
        for i, path in enumerate(paths):
            process_source(
                path, f"source{i + 1}", power_cols, accumulators, counters
            )
        source_description = "; ".join(p.name for p in paths)
        overlap_policy = "Single-source processing; no cross-file overlap policy applied."

    if not accumulators:
        raise ValueError("No valid timestamped records found.")

    timestamps = sorted(accumulators)
    rows = []
    for timestamp in timestamps:
        entry = accumulators[timestamp]
        row = {}
        for i, col in enumerate(power_cols):
            count = entry["count"][i]
            row[col] = entry["sum"][i] / count if count else np.nan
        rows.append(row)

    minute = pd.DataFrame(rows, index=pd.DatetimeIndex(timestamps))
    minute.index.name = "timestamp"

    # Flag unusual values, but preserve them in the output.
    negative_counts = {
        col: int((minute[col] < 0).sum()) for col in power_cols
    }
    extreme_counts = {
        col: int((minute[col] > 10000).sum()) for col in power_cols
    }

    full_index = pd.date_range(
        start=minute.index.min().floor("min"),
        end=minute.index.max().floor("min"),
        freq="1min",
    )
    minute = minute.reindex(full_index)
    minute.index.name = "timestamp"

    missing_before = minute.isna().sum().to_dict()
    limit = int(cfg.get("short_gap_minutes_raw", 2))
    filled = minute.interpolate(
        method="time", limit=limit, limit_area="inside"
    )
    missing_after = filled.isna().sum().to_dict()

    output_dir = resolve_path(cfg["output_dir"])
    table_dir = output_dir / "tables"
    figure_dir = output_dir / "figures"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "source_files": source_description,
        "source_rows_read": counters["source_rows"],
        "invalid_timestamps": counters["invalid_timestamps"],
        "part1_backward_timestamp_steps": counters["part1_backward_steps"],
        "part2_backward_timestamp_steps": counters["part2_backward_steps"],
        "part1_duplicate_rows_collapsed": counters["part1_duplicate_rows"],
        "part2_duplicate_rows_collapsed": counters["part2_duplicate_rows"],
        "part1_conflicting_timestamp_groups_by_channel": str({
            c: counters[f"part1_{c}_conflict_timestamps"] for c in power_cols
        }),
        "part2_conflicting_timestamp_groups_by_channel": str({
            c: counters[f"part2_{c}_conflict_timestamps"] for c in power_cols
        }),
        "start_local_time": str(filled.index.min()),
        "end_local_time": str(filled.index.max()),
        "resampled_rows": len(filled),
        "resampling_interval": "1 minute",
        "aggregation_method": (
            "Mean of available timestamp-level readings within each local minute; "
            "conflicting duplicate timestamp/channel groups excluded for that channel"
        ),
        "source_overlap_policy": overlap_policy,
        "short_gap_rule": f"Time interpolation for up to {limit} consecutive internal minutes",
        "long_gap_rule": "Remaining missing values are retained as NaN",
        "missing_minutes_before_fill": str(missing_before),
        "missing_minutes_after_fill": str(missing_after),
        "negative_readings_flagged_not_removed": str(negative_counts),
        "readings_above_10000W_flagged_not_removed": str(extreme_counts),
        "dst_limitation": (
            "Timestamps are naive UK local wall-clock times. The repeated hour "
            "during the 2013-10-27 DST fall-back cannot be uniquely disambiguated "
            "from these fields; readings in the repeated hour may share the same "
            "one-minute bins."
        ),
    }

    save_table(pd.DataFrame([report]), table_dir / "raw_house1_quality_report.csv")
    filled.to_csv(table_dir / "raw_house1_cleaned_1min.csv", index_label="timestamp")

    plot_cols = cfg.get("raw_plot_appliance_columns") or [
        c for c in power_cols if c != "Aggregate"
    ][:2]
    plot_cols = [
        c for c in plot_cols if c in power_cols and c != "Aggregate"
    ][:2]
    if len(plot_cols) < 2:
        raise ValueError(
            "Please configure two valid appliance columns in raw_plot_appliance_columns."
        )

    # Plot a representative first week. Both plots use the same time window.
    plot_index = filled.index[: 7 * 24 * 60]
    before_plot = minute.reindex(plot_index)
    after_plot = filled.reindex(plot_index)

    for stage, frame in [("before", before_plot), ("after", after_plot)]:
        fig, ax = plt.subplots(figsize=(15, 5))
        frame[["Aggregate"] + plot_cols].plot(ax=ax, linewidth=0.7)
        ax.set_title(f"House 1 {stage} cleaning – first available week")
        ax.set_ylabel("Power (W)")
        ax.set_xlabel("Local timestamp")
        fig.tight_layout()
        fig.savefig(figure_dir / f"raw_house1_{stage}_cleaning.png", dpi=150)
        plt.close(fig)

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        help="Optional single raw House 1 CSV file. Normally both parts are used.",
    )
    args = parser.parse_args()

    cfg = load_config()

    if args.file:
        paths = [Path(args.file)]
    elif cfg.get("raw_house1_file"):
        paths = [resolve_path(cfg["raw_house1_file"])]
    else:

        candidates = [
            p for p in resolve_path(cfg["raw_data_dir"]).glob("*.csv")
            if re.search(r"house[_ -]?1(?:[_ .-]|$)", p.stem, re.IGNORECASE)
            and "clean" not in p.name.lower()
        ]
        paths = sorted(candidates)

    if not paths:
        raise FileNotFoundError("No raw House 1 CSV files found.")
    

    print("Selected raw files:")
    for path in paths:
        print(" -", path.name)
    report = clean_house1(paths, cfg)
    print(pd.Series(report).to_string())


if __name__ == "__main__":
    main()

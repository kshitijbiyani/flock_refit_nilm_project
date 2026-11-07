import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from common import load_config, resolve_path, discover_csvs, read_refit_csv, standardize_refit_frame, house_id_from_path, save_table, safe_energy_kwh

def load_mapping(cfg):
    p = resolve_path(cfg["mapping_file"])
    if not p.exists():
        raise FileNotFoundError(f"Mapping file not found: {p}")
    m = pd.read_csv(p)
    m.columns = [c.strip() for c in m.columns]
    required = {"house_id", "aggregate_column", "washing_machine_column"}
    if not required.issubset(m.columns):
        raise ValueError(f"Mapping CSV needs columns {required}")
    m["house_id"] = pd.to_numeric(m["house_id"], errors="coerce")
    m = m.dropna(subset=["house_id"])
    m["house_id"] = m["house_id"].astype(int)
    m["washing_machine_column"] = m["washing_machine_column"].astype(str).str.strip()
    m = m[m["washing_machine_column"].ne("") & m["washing_machine_column"].str.lower().ne("nan")]
    return m

def load_house(path, mapping_row, rule):
    raw = read_refit_csv(path)
    df, _, _ = standardize_refit_frame(raw)
    agg = mapping_row["aggregate_column"]
    wm_cols = [c.strip() for c in str(mapping_row["washing_machine_column"]).split("|")]
    missing_cols = [c for c in [agg] + wm_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"{path.name}: mapped columns missing {missing_cols}; available: {list(df.columns)}")
    issue_col = next((c for c in df.columns if c.lower() == "issues"), None)
    df = df.drop_duplicates("_time", keep="last").set_index("_time").sort_index()
    if issue_col:
        issue_flag = pd.to_numeric(df[issue_col], errors="coerce").fillna(0).eq(1)
    else:
        issue_flag = pd.Series(False, index=df.index)
    aggregate = pd.to_numeric(df[agg], errors="coerce")
    washing = df[wm_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
    # Official README: Issues=1 means the sum of appliance meters exceeds aggregate.
    aggregate = aggregate.mask(issue_flag)
    washing = washing.mask(issue_flag)
    x = pd.DataFrame({"aggregate_w": aggregate, "washing_machine_w": washing}).resample(rule).mean()
    x["issues_flagged"] = issue_flag.astype(int).resample(rule).max().fillna(0)
    x["house_id"] = int(mapping_row["house_id"])
    return x


def detect_cycles(series, threshold, min_minutes, merge_gap):
    """
    Detect washing-machine operating cycles.

    Missing readings split the timeline into separate observed segments.
    Short inactive gaps are merged only within an observed segment.
    """
    rows = []

    # A missing reading is unknown, not zero power.
    valid = series.notna()

    # Identify continuous segments containing observed readings.
    segment_groups = (valid != valid.shift()).cumsum()

    for _, segment in series[valid].groupby(segment_groups[valid]):

        active = segment >= threshold

        # Merge short inactive gaps within this observed segment.
        if merge_gap > 0:
            inactive = ~active
            gap_groups = (inactive != inactive.shift()).cumsum()

            for _, idx in inactive.groupby(gap_groups).groups.items():
                idx = list(idx)

                is_inactive = not active.loc[idx[0]]
                is_internal = (
                    idx[0] != active.index[0]
                    and idx[-1] != active.index[-1]
                )

                if is_inactive and is_internal and len(idx) <= merge_gap:
                    active.loc[idx] = True

        # Identify continuous active periods.
        cycle_groups = (active != active.shift()).cumsum()

        for _, idx in active.groupby(cycle_groups).groups.items():
            idx = list(idx)

            if not active.loc[idx[0]]:
                continue

            duration = len(idx)

            if duration < min_minutes:
                continue

            vals = segment.loc[idx].clip(lower=0)

            rows.append({
                "start": idx[0],
                "end": idx[-1],
                "duration_minutes": duration,
                "peak_power_w": float(vals.max()),
                "energy_kwh": safe_energy_kwh(vals),
                "hour": idx[0].hour,
                "day_of_week": idx[0].day_name()
            })

    return pd.DataFrame(rows)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-houses", type=int, default=None)
    args = parser.parse_args()
    cfg = load_config()
    mapping = load_mapping(cfg)
    files = discover_csvs(cfg["cleaned_data_dir"])
    if not files:
        raise FileNotFoundError("Put extracted official cleaned REFIT CSV files in data/cleaned/.")
    lookup = {house_id_from_path(p): p for p in files if house_id_from_path(p) is not None}
    rows, cycles_all, availability = [], [], []
    figdir = resolve_path(cfg["output_dir"]) / "figures"
    tabdir = resolve_path(cfg["output_dir"]) / "tables"
    figdir.mkdir(parents=True, exist_ok=True); tabdir.mkdir(parents=True, exist_ok=True)
    selected = mapping.to_dict("records")
    if args.max_houses:
        selected = selected[:args.max_houses]
    for mr in selected:
        hid = int(mr["house_id"])
        if hid not in lookup:
            print(f"Skipping House {hid}: no matching cleaned CSV found.")
            continue
        print(f"Loading cleaned House {hid}...")
        x = load_house(lookup[hid], mr, cfg["resample_rule"])
        # Capture missingness before excluding unlabelled rows from cycle analysis.
        missing_wm_minutes = int(x["washing_machine_w"].isna().sum())
        missing_aggregate_minutes = int(x["aggregate_w"].isna().sum())
        # x = x.dropna(subset=["aggregate_w", "washing_machine_w"])
        # Keep missing timestamps in the timeline; do not treat missing readings as appliance-off.
        # We will handle missing values safely during cycle detection.
        cycles = detect_cycles(x["washing_machine_w"], float(cfg["active_threshold_w"]),
                               int(cfg["minimum_active_minutes"]), int(cfg["merge_inactive_gap_minutes"]))
        if not cycles.empty:
            cycles["house_id"] = hid
            cycles_all.append(cycles)
        
        valid_wm = x["washing_machine_w"].notna()
        valid_aggregate = x["aggregate_w"].notna()

        observed_wm_minutes = int(valid_wm.sum())
        total_minutes = len(x)

        availability.append({
            "house_id": hid,
            "file": lookup[hid].name,
            "start": x.index.min(),
            "end": x.index.max(),
            "total_timeline_minutes": total_minutes,
            "observed_wm_minutes": observed_wm_minutes,
            "wm_coverage_pct": round(
                observed_wm_minutes / total_minutes * 100, 2
            ) if total_minutes else 0,
            "missing_wm_minutes": missing_wm_minutes,
            "missing_aggregate_minutes": missing_aggregate_minutes,
            "zero_or_off_minutes": int(
                (x.loc[valid_wm, "washing_machine_w"]
                 < cfg["active_threshold_w"]).sum()
            ),
            "detected_cycles": len(cycles)
        })

        x["house_id"] = hid
        rows.append(x)

        # Representative 24h window with the most observed washing activity.
        daily = x["washing_machine_w"].resample("D").sum()
        if len(daily) and daily.max() > 0:
            day = daily.idxmax()
            sample = x.loc[day: day + pd.Timedelta(days=1)]
            fig, ax = plt.subplots(figsize=(14, 4))
            sample[["aggregate_w", "washing_machine_w"]].plot(ax=ax, linewidth=0.8)
            ax.set_title(f"House {hid}: representative 24-hour aggregate and washing-machine trace")
            ax.set_ylabel("Power (W)"); fig.tight_layout()
            fig.savefig(figdir / f"house_{hid}_representative_24h.png", dpi=150); plt.close(fig)

        if not cycles.empty:
            c = cycles.sort_values("energy_kwh", ascending=False).iloc[0]
            s = x.loc[c["start"]:c["end"], "washing_machine_w"]
            fig, ax = plt.subplots(figsize=(12, 4))
            s.plot(ax=ax, linewidth=1)
            ax.set_title(f"House {hid}: example detected washing-machine cycle")
            ax.set_ylabel("Power (W)"); fig.tight_layout()
            fig.savefig(figdir / f"house_{hid}_example_cycle.png", dpi=150); plt.close(fig)

    if not rows:
        raise RuntimeError("No valid mapped households were loaded. Check mapping and file names.")
    all_data = pd.concat(rows).sort_index()
    availability_df = pd.DataFrame(availability)
    cycles_df = pd.concat(cycles_all, ignore_index=True) if cycles_all else pd.DataFrame()
    save_table(availability_df, tabdir / "washing_machine_availability.csv")
    save_table(cycles_df, tabdir / "washing_machine_cycles.csv")
    # Parquet is preferred for compact storage; CSV fallback keeps the pipeline
    # runnable if an optional parquet engine is unavailable in the environment.
    try:
        all_data.to_parquet(tabdir / "cleaned_1min_mapped_households.parquet")
    except (ImportError, ModuleNotFoundError):
        all_data.to_csv(tabdir / "cleaned_1min_mapped_households.csv", index_label="timestamp")

    
    # Hour-of-day and day-of-week usage.
    # First calculate usage separately for each household.
    # Missing readings remain NaN and are excluded from the denominator.

    usage_data = all_data[["house_id", "washing_machine_w"]].copy()
    usage_data["hour"] = usage_data.index.hour
    usage_data["day_of_week"] = usage_data.index.day_name()

    usage_data["active"] = np.where(
        usage_data["washing_machine_w"].notna(),
        (
            usage_data["washing_machine_w"]
            >= float(cfg["active_threshold_w"])
        ).astype(float),
        np.nan
    )

    # Equal household weighting: calculate each household's active fraction,
    # then average those household-level fractions.
    by_hour = (
        usage_data.groupby(["house_id", "hour"])["active"]
        .mean()
        .groupby("hour")
        .mean()
        .rename("active_minute_fraction")
    )

    day_order = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"
    ]

    by_day = (
        usage_data.groupby(["house_id", "day_of_week"])["active"]
        .mean()
        .groupby("day_of_week")
        .mean()
        .reindex(day_order)
        .rename("active_minute_fraction")
    )

    by_hour.to_csv(tabdir / "usage_by_hour.csv")
    by_day.to_csv(tabdir / "usage_by_day_of_week.csv")

    fig, ax = plt.subplots(figsize=(10, 4))
    by_hour.plot(kind="bar", ax=ax)
    ax.set_title("Washing-machine active-minute fraction by hour")
    ax.set_ylabel("Mean household active-minute fraction")
    ax.set_xlabel("Hour of day")
    fig.tight_layout()
    fig.savefig(figdir / "washing_machine_usage_by_hour.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    by_day.plot(kind="bar", ax=ax)
    ax.set_title("Washing-machine active-minute fraction by day of week")
    ax.set_ylabel("Mean household active-minute fraction")
    ax.set_xlabel("Day of week")
    fig.tight_layout()
    fig.savefig(figdir / "washing_machine_usage_by_day.png", dpi=150)
    plt.close(fig)


    if not cycles_df.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        sns.boxplot(data=cycles_df, x="house_id", y="energy_kwh", ax=ax)
        ax.set_title("Washing-machine cycle energy by household"); ax.set_ylabel("Energy per detected cycle (kWh)")
        fig.tight_layout(); fig.savefig(figdir / "cycle_energy_by_house.png", dpi=150); plt.close(fig)
        fig, ax = plt.subplots(figsize=(10, 4))
        sns.boxplot(data=cycles_df, x="house_id", y="duration_minutes", ax=ax)
        ax.set_title("Washing-machine cycle duration by household"); ax.set_ylabel("Duration (minutes)")
        fig.tight_layout(); fig.savefig(figdir / "cycle_duration_by_house.png", dpi=150); plt.close(fig)
    print("EDA complete. See outputs/tables and outputs/figures.")

if __name__ == "__main__":
    main()

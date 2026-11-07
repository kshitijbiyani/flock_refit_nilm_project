from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def load_config():
    with open(ROOT / "config" / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def resolve_path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p

def discover_csvs(folder):
    folder = resolve_path(folder)
    return sorted([p for p in folder.rglob("*.csv") if p.is_file()])

def read_refit_csv(path, chunksize=None):
    """Read REFIT CSV robustly; normalize common column-name variants."""
    kwargs = {"low_memory": False}
    if chunksize:
        kwargs["chunksize"] = chunksize
        return pd.read_csv(path, **kwargs)
    df = pd.read_csv(path, **kwargs)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def identify_time_column(df):
    candidates = ["Time", "DateTime", "Datetime", "timestamp", "Timestamp", "time"]
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(f"No recognized timestamp column. Available: {list(df.columns)}")

def parse_time_column(series):
    # REFIT CSVs commonly contain a readable DateTime column. Numeric Unix
    # timestamps are also supported, with seconds/milliseconds inference.
    if pd.api.types.is_numeric_dtype(series):
        x = pd.to_numeric(series, errors="coerce")
        median = x.dropna().median() if x.notna().any() else np.nan
        unit = "ms" if median > 1e11 else "s"
        return pd.to_datetime(x, unit=unit, errors="coerce")
    return pd.to_datetime(series, errors="coerce", dayfirst=False)

def find_power_columns(df):
    return [c for c in df.columns if c.lower() == "aggregate" or c.lower().startswith("appliance") or c.lower().startswith("iam")]

def standardize_refit_frame(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    tcol = identify_time_column(df)
    df["_time"] = parse_time_column(df[tcol])
    power_cols = find_power_columns(df)
    for c in power_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["_time"]).sort_values("_time")
    return df, tcol, power_cols

def house_id_from_path(path):
    import re
    m = re.search(r"house[_-]?(\d+)", Path(path).name, flags=re.I)
    return int(m.group(1)) if m else None

def save_table(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

def safe_energy_kwh(power_w_series):
    # For 1-minute average power, Wh = sum(W * 1/60); convert to kWh.
    return float(power_w_series.clip(lower=0).sum() / 60.0 / 1000.0)

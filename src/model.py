import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, precision_recall_fscore_support
from pathlib import Path
from common import load_config, resolve_path, discover_csvs, read_refit_csv, standardize_refit_frame, house_id_from_path, save_table
from cleaned_eda import load_mapping

def make_features(x, cfg):
    z = x.copy()
    for lag in cfg["lags_minutes"]:
        z[f"agg_lag_{lag}"] = z["aggregate_w"].shift(lag)
    for win in cfg["rolling_windows_minutes"]:
        z[f"agg_roll_mean_{win}"] = z["aggregate_w"].rolling(win, min_periods=win).mean()
        z[f"agg_roll_std_{win}"] = z["aggregate_w"].rolling(win, min_periods=win).std()
    minute_of_day = z.index.hour * 60 + z.index.minute
    z["hour_sin"] = np.sin(2 * np.pi * minute_of_day / 1440)
    z["hour_cos"] = np.cos(2 * np.pi * minute_of_day / 1440)
    z["dow_sin"] = np.sin(2 * np.pi * z.index.dayofweek / 7)
    z["dow_cos"] = np.cos(2 * np.pi * z.index.dayofweek / 7)
    return z

def load_model_data(cfg, max_houses=None):
    mapping = load_mapping(cfg)
    paths = discover_csvs(cfg["cleaned_data_dir"])
    lookup = {house_id_from_path(p): p for p in paths if house_id_from_path(p) is not None}
    frames = []
    selected = mapping.to_dict("records")
    if max_houses:
        selected = selected[:max_houses]
    for mr in selected:
        hid = int(mr["house_id"])
        if hid not in lookup:
            continue
        df = read_refit_csv(lookup[hid])
        df, _, _ = standardize_refit_frame(df)
        a = mr["aggregate_column"]
        w_cols = [c.strip() for c in str(mr["washing_machine_column"]).split("|")]
        missing_cols = [c for c in [a] + w_cols if c not in df.columns]
        if missing_cols:
            print(f"Skipping house {hid}: mapped columns unavailable: {missing_cols}")
            continue
        issue_col = next((c for c in df.columns if c.lower() == "issues"), None)
        df = df.drop_duplicates("_time", keep="last").set_index("_time").sort_index()
        aggregate = pd.to_numeric(df[a], errors="coerce")
        target = df[w_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
        if issue_col:
            issue_flag = pd.to_numeric(df[issue_col], errors="coerce").fillna(0).eq(1)
        else:
            issue_flag = pd.Series(False, index=df.index)
        x = pd.DataFrame({"aggregate_w": aggregate, "target_w": target}).resample(cfg["resample_rule"]).mean()
        # Exclude an entire minute if any native sample carries Issues=1.
        issue_minutes = issue_flag.astype(int).resample(cfg["resample_rule"]).max().fillna(0).eq(1)
        x.loc[issue_minutes, ["aggregate_w", "target_w"]] = np.nan
        x["house_id"] = hid
        
        # Official cleaned zeros can represent either off or long missing periods.
        # Keep them, but document this ambiguity in DATA.md and RESULTS.md.

        # Preserve missing minutes so lag and rolling features respect real time.
        x = x.replace([np.inf, -np.inf], np.nan)
        x["aggregate_w"] = x["aggregate_w"].clip(lower=0)
        x["target_w"] = x["target_w"].clip(lower=0)

        # Create time-series features before removing incomplete training rows.
        # Missing readings will invalidate affected lag/rolling windows.
        f = make_features(x, cfg).dropna()

        frames.append(f)
        print(f"Prepared House {hid}: {len(f):,} usable minute rows")
    if not frames:
        raise RuntimeError("No mapped households loaded. Check config/appliance_mapping.csv.")
    return pd.concat(frames).sort_index()

def temporal_split(data, cfg):
    # Split each household chronologically so future observations cannot leak
    # into training. The final fraction of each household is the untouched test.
    train_parts, val_parts, test_parts = [], [], []
    for hid, g in data.groupby("house_id"):
        g = g.sort_index()
        n = len(g)
        i1 = int(n * cfg["train_fraction"])
        i2 = int(n * (cfg["train_fraction"] + cfg["validation_fraction"]))
        if i1 < 1 or i2 <= i1 or i2 >= n:
            continue
        train_parts.append(g.iloc[:i1]); val_parts.append(g.iloc[i1:i2]); test_parts.append(g.iloc[i2:])
    if not train_parts:
        raise RuntimeError("Not enough rows per household for configured chronological split.")
    return pd.concat(train_parts), pd.concat(val_parts), pd.concat(test_parts)

def metrics(y, pred, threshold):
    y = np.asarray(y); pred = np.asarray(pred)
    p, r, f1, _ = precision_recall_fscore_support(y >= threshold, pred >= threshold, average="binary", zero_division=0)
    return {
        "mae_w": mean_absolute_error(y, pred),
        "rmse_w": mean_squared_error(y, pred) ** 0.5,
        "r2": r2_score(y, pred),
        "actual_energy_kwh": float(np.clip(y, 0, None).sum() / 60000),
        "predicted_energy_kwh": float(np.clip(pred, 0, None).sum() / 60000),
        "absolute_energy_error_percent": float(abs(np.clip(pred,0,None).sum()-np.clip(y,0,None).sum()) / max(np.clip(y,0,None).sum(), 1e-9) * 100),
        "active_precision": p, "active_recall": r, "active_f1": f1
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-houses", type=int, default=None)
    args = parser.parse_args()
    cfg = load_config()
    data = load_model_data(cfg, args.max_houses)
    train, val, test = temporal_split(data, cfg)

    print(
    "Validation active-minute fraction:",
    round((val["target_w"] >= cfg["active_threshold_w"]).mean() * 100, 2),
    "%"
)

    print(
    "Test active-minute fraction:",
    round((test["target_w"] >= cfg["active_threshold_w"]).mean() * 100, 2),
    "%"
)


    features = [c for c in data.columns if c not in ["target_w", "house_id"]]
    # Select model family using validation MAE only; test is evaluated once.
    candidates = {
        "HistGradientBoosting": HistGradientBoostingRegressor(max_iter=150, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0, random_state=cfg["random_state"]),
        "RandomForest": RandomForestRegressor(n_estimators=100, min_samples_leaf=3, max_features=0.8, n_jobs=-1, random_state=cfg["random_state"])
    }
    # Limit training rows per household while preserving the natural
    # proportion of active and inactive washing-machine minutes.
    cap = int(cfg.get("max_training_rows_per_house", 0) or 0)

    if cap > 0:
        sampled = []
        rng = np.random.default_rng(cfg["random_state"])

        for hid, g in train.groupby("house_id"):
            if len(g) <= cap:
                sampled.append(g)
            else:
                chosen = rng.choice(
                    len(g),
                    size=cap,
                    replace=False
                )
                sampled.append(g.iloc[chosen].sort_index())

        train = pd.concat(sampled).sort_index()

        print(f"Training rows after per-house cap: {len(train):,}")
        print(
            "Training active-minute fraction after sampling:",
            f"{(train['target_w'] >= cfg['active_threshold_w']).mean():.2%}"
        )

    scored = []
    for name, model in candidates.items():
        model.fit(train[features], train["target_w"])
        pred = np.clip(model.predict(val[features]), 0, None)
        scored.append((mean_absolute_error(val["target_w"], pred), name, model))
        print(f"{name} validation MAE: {scored[-1][0]:.3f} W")
    _, best_name, best_model = min(scored, key=lambda z: z[0])
    test_pred = np.clip(best_model.predict(test[features]), 0, None)
    result = metrics(test["target_w"], test_pred, cfg["active_threshold_w"])
    result["selected_model"] = best_name
    result["test_rows"] = len(test)
    result["test_households"] = int(test["house_id"].nunique())

    
    # Calculate evaluation metrics separately for each household.
    household_results = []

    test_evaluation = test[["target_w", "house_id"]].copy()
    test_evaluation["predicted_w"] = test_pred

    for hid, house_data in test_evaluation.groupby("house_id"):
        house_metrics = metrics(
            house_data["target_w"],
            house_data["predicted_w"],
            cfg["active_threshold_w"]
        )

        house_metrics["house_id"] = int(hid)
        house_metrics["test_rows"] = len(house_data)
        house_metrics["selected_model"] = best_name

        household_results.append(house_metrics)

    household_metrics_df = pd.DataFrame(household_results)

    household_metrics_df = household_metrics_df[
        [
            "house_id",
            "selected_model",
            "test_rows",
            "mae_w",
            "rmse_w",
            "r2",
            "actual_energy_kwh",
            "predicted_energy_kwh",
            "absolute_energy_error_percent",
            "active_precision",
            "active_recall",
            "active_f1"
        ]
    ]

    household_metrics_df.to_csv(
        resolve_path(cfg["output_dir"]) / "tables" / "model_household_metrics.csv",
        index=False
    )

    print("\nHousehold-level test metrics:")
    print(household_metrics_df.round(3).to_string(index=False))

    out = resolve_path(cfg["output_dir"]); (out/"tables").mkdir(parents=True, exist_ok=True)
    save_table(pd.DataFrame([result]), out/"tables"/"model_metrics.csv")
    joblib.dump({"model": best_model, "features": features, "model_name": best_name}, out/"model.joblib")

    comparison = test[["target_w", "aggregate_w", "house_id"]].copy()
    comparison["predicted_w"] = test_pred
    comparison.to_csv(out/"tables"/"test_predictions.csv", index_label="timestamp")
    # Plot up to 48 consecutive hours per test home, preferring a period with activity.
    figdir = out/"figures"; figdir.mkdir(parents=True, exist_ok=True)
    for hid, g in comparison.groupby("house_id"):
        daily = g["target_w"].resample("D").sum()
        if not len(daily): continue
        start = daily.idxmax()
        sample = g.loc[start:start + pd.Timedelta(hours=48)]
        if sample.empty: continue
        fig, ax = plt.subplots(figsize=(14, 4))
        sample[["target_w", "predicted_w"]].rename(columns={"target_w":"Actual", "predicted_w":"Predicted"}).plot(ax=ax, linewidth=0.9)
        ax.set_title(f"House {hid}: actual vs predicted washing-machine power (held-out test)")
        ax.set_ylabel("Power (W)"); fig.tight_layout()
        fig.savefig(figdir/f"house_{hid}_actual_vs_predicted.png", dpi=150); plt.close(fig)
    print("Selected model:", best_name)
    print(pd.Series(result).to_string())
    print("Saved outputs/model.joblib and held-out predictions.")

if __name__ == "__main__":
    main()

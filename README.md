# REFIT Data Cleaning & Washing-Machine NILM

A reproducible take-home project for the Flock Energy Data Science assignment. It contains a raw House 1 cleaning workflow, multi-house washing-machine EDA, and a supervised NILM regression benchmark.

**Current analysis coverage:** raw House 1 Part 1 and Part 2; official cleaned REFIT data for 19 mapped households (Houses 1–11, 13, and 15–21). Houses 12 and 14 are not present in the supplied cleaned files used for this run.

> **Important:** The dataset is not redistributed in this repository. Download the official REFIT raw and cleaned archives from the University of Strathclyde and extract the CSVs locally. The first run is not complete until the appliance-channel mapping in `config/appliance_mapping.csv` has been verified against the official metadata/readme.

## 1. Repository structure

```text
flock_refit_nilm/
├── config/
│   ├── config.yaml
│   └── appliance_mapping.csv
├── data/
│   ├── raw/                 # raw House 1 CSV (not committed)
│   └── cleaned/             # official CLEAN_House*.csv files (not committed)
├── outputs/
│   ├── figures/
│   └── tables/
├── src/
│   ├── clean_raw.py
│   ├── cleaned_eda.py
│   ├── model.py
│   ├── common.py
│   └── run_all.py
├── DATA.md
├── RESULTS.md
├── Recommendation.md
└── requirements.txt
```

## 2. Dataset setup

Use the official REFIT dataset, University of Strathclyde:
- Raw: https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/
- Cleaned: https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements-cleaned/
- Dataset paper: https://doi.org/10.1038/sdata.2016.122

Extract the raw House 1 CSV into `data/raw/`. Extract the official cleaned household CSVs into `data/cleaned/`. The cleaned archive is large; do not commit the archives or extracted CSVs to GitHub.

## 3. Verify appliance channel mapping (mandatory)

The channel number is not globally consistent across households and appliance identities can change during monitoring. Use `CLEAN_READ_ME_081116.txt` and `MetaData_Tables.xlsx` from the official release to identify the washing-machine channel for each home and its valid period.

The mapping used in the current analysis is recorded in `config/appliance_mapping.csv`. House 1 uses `Appliance5` (the separate `Appliance4` channel is a washer-dryer). House 4 has two identified washing-machine channels; the code sums both using the `|` separator. House 8 uses `Appliance4` (Appliance3 is identified as washer-dryer), and House 9 uses `Appliance3` (Appliance2 is identified as washer-dryer). House 12 and House 14 are absent from the supplied cleaned files. House 13 is included on Appliance3, but its documented 25 March 2015 appliance change is a potential signature-drift boundary and should be considered when interpreting results.

For each row, `washing_machine_column` is the exact CSV column name; multiple channels can be joined with `|`. **Issues flag handling:** the EDA and NILM preprocessing both use the official `Issues` flag. In EDA, native readings marked `Issues=1` are masked before one-minute resampling. In the model pipeline, if any native sample in a minute has `Issues=1`, both aggregate input and washing-machine target for that minute are set to missing. The availability summary does not report a separate count of issue-flagged minutes.

## 4. Environment

Python 3.10 is the version used for this project run. The environment was created with the Windows Python launcher (`py -3.10 -m venv .venv`). Use the dependency versions declared in `requirements.txt`; avoid mixing packages from a different global Python environment with this project's virtual environment.

```bash
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
# Windows Command Prompt
.venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Run

From the repository root:

```bash
python src/clean_raw.py
python src/cleaned_eda.py
python src/model.py
```

Or run the full pipeline:

```bash
python src/run_all.py
```

If the raw House 1 CSV is not auto-detected, provide it explicitly:

```bash
python src/clean_raw.py --file "data/raw/House1.csv"
```

For a quick smoke test after mapping a few homes:

```bash
python src/cleaned_eda.py --max-houses 2
python src/model.py --max-houses 2
```

The full analysis is intended to use every eligible mapped household. Processing each large CSV separately reduces peak memory use, although the model combines engineered 1-minute rows in memory. If RAM is limited, reduce `max_training_rows_per_house` or extend the implementation to stream training batches.

## 6. Outputs

- `outputs/tables/raw_house1_quality_report.csv`
- `outputs/tables/raw_house1_cleaned_1min.csv`
- `outputs/tables/washing_machine_availability.csv`
- `outputs/tables/washing_machine_cycles.csv`
- `outputs/tables/cleaned_1min_mapped_households.parquet` (or `.csv` if no Parquet engine is available)
- `outputs/tables/model_metrics.csv`
- `outputs/tables/model_household_metrics.csv`
- `outputs/tables/test_predictions.csv`
- `outputs/figures/*.png` (cleaning plots, usage/cycle comparisons, and per-household representative-day, example-event and actual-versus-predicted plots)
- `outputs/model.joblib`

The mapped one-minute cleaned dataset is written as a Parquet or CSV file depending on the available Parquet engine. The exact filename/extension is determined by the pipeline output. The output tables and figure inventory are described further in `DATA.md` and `RESULTS.md`.

## 7. Method and assumptions

- Raw House 1: parse timestamps, sort records, and resolve duplicate timestamps at the individual channel level. Where duplicate readings for a channel conflict, that channel's value is set to missing rather than arbitrarily retaining the last row. Resample to 1-minute mean power, interpolate only short internal gaps of up to 2 consecutive minutes, and leave longer gaps missing.
- Raw source overlap: retain Part 1 during the overlap and use Part 2 only after the maximum valid Part 1 timestamp. This is a deterministic source-selection rule, not a claim that Part 1 is more accurate.
- Extreme readings: negative readings were not observed in the reported quality checks. Readings above 10,000 W are flagged but retained; they are not automatically removed by the current raw-cleaning workflow.
- Official cleaned data: use the household-specific appliance mapping and resample aggregate and washing-machine channels to 1-minute means. In EDA, native readings marked `Issues=1` are masked before resampling. In model preprocessing, any one-minute bin containing at least one native `Issues=1` sample has both aggregate input and washing-machine target masked as missing. The official cleaned release also has upstream gap and outlier handling, including zero-filled long gaps; see `DATA.md`.
- Cycle detection: threshold-based, default 10 W, bridge inactive gaps of up to 2 minutes, and retain events lasting at least 5 minutes. These are operational definitions, not ground-truth cycle annotations.
- Model: supervised regression from aggregate-derived lag/rolling/time features to washing-machine watts. HistGradientBoosting and RandomForest are compared on validation MAE.
- Validation: chronological per-house split (70% train, 15% validation, 15% test); test is held out until model selection is complete. This evaluates later time periods within the same households, not transfer to entirely unseen households.
- Metrics: MAE/RMSE in watts, R², energy error, and active-state precision/recall/F1 at the same threshold.

## 8. Limitations and improvements

The official cleaned data's zero-filled long gaps can be indistinguishable from genuine appliance-off periods without separate outage masks. The EDA and model preprocessing use the `Issues` flag to exclude flagged readings/minutes as described in Section 7; however, the availability summary does not separately quantify the number of issue-flagged minutes. Appliance changes, missing labels, overlapping loads, household-specific signatures and unmetered loads limit generalization. One-minute averaging suppresses short transients. UK household behaviour and appliance characteristics may not transfer directly to India.

The current model's held-out test results are: MAE 9.30 W, RMSE 85.52 W, R² 0.203, absolute total-energy error 8.87%, and active-state F1 0.208. The relatively modest energy error should not be interpreted as reliable minute-level or cycle-level detection: active-state precision is 13.67% and recall is 43.33%. See `RESULTS.md` for the complete metrics and household-level variation.

Potential next steps: compare with a Seq2Point CNN/TCN; evaluate leave-one-house-out transfer; include explicit missingness masks; test 15/30-minute aggregation; use event-level cycle matching; quantify uncertainty; and validate with Indian smart-meter/appliance datasets.

## 9. AI tools

ChatGPT was used to support implementation planning, code review/debugging discussions, and documentation. Cursor was used as the development environment and code editor. The project should be described as validated only to the extent that the documented scripts were actually run and their outputs inspected; AI assistance is not a substitute for independent execution and verification.

## 10. Reproducibility notes

- Run commands from the repository root so paths in `config/config.yaml` resolve correctly.
- Keep the raw and official cleaned CSV files local; they are large and are not included in this repository.
- Check `config/appliance_mapping.csv` before running the full EDA/model workflow.
- The current analysis uses one-minute data and the settings in `config/config.yaml`. Record any changes to thresholds, household mappings, sampling, or split settings when comparing runs.
- Generated figures and tables are derived outputs. If you regenerate them, ensure that `DATA.md` and `RESULTS.md` still describe the latest run rather than a mixture of runs.

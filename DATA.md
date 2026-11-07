# DATA – REFIT coverage and quality

## Source and licence

The REFIT Electrical Load Measurements dataset was collected from 20 UK households in Loughborough. The dataset contains aggregate and appliance-level active-power measurements. The original measurements are approximately 8-second data; this project resamples the relevant channels to one-minute mean power for cleaning, EDA and NILM.

The dataset is associated with:

Murray, D., Stankovic, L. & Stankovic, V. (2017). *An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study*. Scientific Data. https://doi.org/10.1038/sdata.2016.122

The dataset is released under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence. Check the dataset landing pages and accompanying terms when redistributing the source data; this repository should contain code and derived outputs rather than republishing the raw dataset unless permitted.

Official source pages:
- Raw: https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/
- Cleaned: https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements-cleaned/

## Coverage used in this project

The supplied files include raw data for House 1 (Part 1 and Part 2) and official cleaned data for 19 households: Houses 1–11, 13, and 15–21. Houses 12 and 14 are not present in the supplied cleaned files. Therefore, the EDA and NILM results cover 19 households, not all 20 REFIT homes.

| Analysis | Households/files used | Period | Native sampling | Analysis sampling |
|---|---|---|---|---|
| Raw cleaning | Raw House 1, Part 1 and Part 2 | 2013-10-09 14:06 to 2015-07-10 11:56 | Approximately 8 seconds | 1 minute |
| Washing-machine EDA | 19 mapped official cleaned households: 1–11, 13, 15–21 | Combined observed range: 2013-09-17 to 2015-07-10; household-specific coverage is in `outputs/tables/washing_machine_availability.csv` | Approximately 8 seconds in the source dataset | 1 minute |
| NILM | Same 19 mapped households | Per-house chronological 70% train / 15% validation / 15% test split | Approximately 8 seconds in the source dataset | 1 minute |

The raw House 1 cleaner processed 8,518,763 source rows and produced 920,031 one-minute rows. The EDA availability calculation covers 14,960,575 household-timeline minutes across the 19 eligible households.

Do not interpret the combined date range as continuous, complete coverage for every household. Use the per-household availability table for household-specific start/end dates and coverage.

## Raw House 1 cleaning decisions

The raw House 1 pipeline processes `RAW_House1_Part1.csv` and `RAW_House1_Part2.csv`. It standardises timestamps, sorts records chronologically, resolves duplicate timestamps at the channel level, resamples to one-minute mean power, and records data-quality issues.

### Timestamp ordering, overlap and duplicates

- Invalid timestamps reported: 0.
- Backward timestamp steps in Part 1: 2.
- Backward timestamp steps in Part 2: 0.
- Duplicate rows collapsed in Part 1: 645,418.
- Duplicate rows collapsed in Part 2: 0.
- During the source overlap, Part 1 is retained and Part 2 is used only after the maximum valid Part 1 timestamp. This is a deterministic source-selection policy, not evidence that Part 1 is more accurate.

The cleaner does **not** simply retain the last duplicate record. Duplicate timestamps are grouped and resolved separately for each power channel. Where duplicate values for a channel agree, the grouped value is retained; where that channel has conflicting values, that channel's value is set to missing rather than choosing an arbitrary reading. This means a conflict in one channel does not automatically discard all other channels at that timestamp.

The reported conflicting timestamp/channel groups in Part 1 are:

| Channel | Conflicting groups |
|---|---:|
| Aggregate | 33,206 |
| Appliance1 | 3,365 |
| Appliance2 | 5,249 |
| Appliance3 | 6,106 |
| Appliance4 | 67 |
| Appliance5 | 531 |
| Appliance6 | 213 |
| Appliance7 | 1,747 |
| Appliance8 | 3,402 |
| Appliance9 | 959 |

Part 2 reported zero conflicting groups across these channels. The duplicate/conflict counts are those reported by the current pipeline; duplicate groups that span processing-chunk boundaries may not be fully represented in the per-chunk conflict counts.

### Resampling, missing readings and interpolation

The data are resampled to one-minute mean power. Internal gaps of up to two consecutive minutes are time-interpolated. Longer gaps remain missing (`NaN`) and are not filled with zero, because zero would imply no consumption.

| Channel | Missing before filling | Missing after filling |
|---|---:|---:|
| Aggregate | 122,231 | 120,733 |
| Appliance1 | 124,646 | 121,954 |
| Appliance2 | 125,469 | 122,637 |
| Appliance3 | 123,663 | 122,110 |
| Appliance4 | 122,411 | 120,886 |
| Appliance5 | 130,553 | 126,629 |
| Appliance6 | 122,274 | 120,777 |
| Appliance7 | 122,205 | 120,713 |
| Appliance8 | 123,832 | 121,617 |
| Appliance9 | 212,987 | 210,550 |

For the Aggregate channel, 1,498 missing minutes were filled and 120,733 remained missing after interpolation.

The quality report does not provide a median native sampling interval or a count of irregular native intervals. These values are not inferred from the one-minute resampled output.

### Negative and extreme readings

- Negative readings flagged: 0 across all channels.
- Readings above 10,000 W were flagged but **retained**, not automatically removed:

| Channel | Readings above 10,000 W |
|---|---:|
| Aggregate | 1,688 |
| Appliance1 | 13 |
| Appliance2 | 4 |
| Appliance3 | 3 |
| Appliance4 | 32 |
| Appliance5 | 4 |
| Appliance6 | 0 |
| Appliance7 | 8 |
| Appliance8 | 9 |
| Appliance9 | 1 |

The 10,000 W threshold is a broad screening threshold used to flag extreme readings for review. It is not a validated physical maximum for every channel. Retaining flagged values preserves the source evidence, but these observations may influence summary statistics and model fitting.

### Daylight-saving-time limitation

The source timestamps are treated as naive UK local wall-clock times. The repeated hour during the 2013-10-27 daylight-saving transition cannot be uniquely disambiguated from the available naive timestamps. Readings in the repeated hour may therefore share the same one-minute bins. This is a known limitation of the current timestamp treatment.

## Official cleaned data caveats

This project uses the official cleaned REFIT release for washing-machine EDA and NILM. The official cleaned data have already undergone upstream processing. The accompanying cleaned-data documentation describes, among other steps:

- merging duplicate timestamps;
- setting individual-appliance monitor readings above 4,000 W to zero;
- processing IAM channels to represent one appliance where possible;
- forward-filling NaN gaps shorter than two minutes and setting longer gaps to zero.

These are inherited properties of the official cleaned data; this project does not reverse the official cleaning process. Consequently, a zero in an official cleaned appliance channel may represent genuine appliance inactivity or a longer missing-data interval. Without a reliable separate outage mask, those cases cannot always be distinguished. This can inflate apparent off-time and affect event counts.

**Issues flag:** the official cleaned files include an `Issues` column. The EDA masks native aggregate and washing-machine readings where `Issues=1` before one-minute resampling. The model pipeline applies a stricter minute-level rule: if any native sample within a one-minute bin has `Issues=1`, both aggregate input and washing-machine target for that minute are set to missing. The availability summary does not separately report the number of issue-flagged native samples or one-minute bins, so no count is claimed here.

## Appliance mapping

Appliance channel identities are household-specific. The mapping used by the analysis is stored in `config/appliance_mapping.csv` and was populated from the supplied REFIT cleaned-data appliance documentation. The table below records the mapping used by the current project.

| House | Washing-machine channel(s) | Mapping status | Notes |
|---:|---|---|---|
| 1 | Appliance5 | Mapped | Appliance4 is a separate washer-dryer channel |
| 2 | Appliance2 | Mapped | |
| 3 | Appliance6 | Mapped | |
| 4 | Appliance4 + Appliance5 | Mapped | Both identified washer channels are summed |
| 5 | Appliance3 | Mapped | |
| 6 | Appliance2 | Mapped | |
| 7 | Appliance5 | Mapped | |
| 8 | Appliance4 | Mapped | Appliance3 is identified as washer-dryer |
| 9 | Appliance3 | Mapped | Appliance2 is identified as washer-dryer |
| 10 | Appliance5 | Mapped | |
| 11 | Appliance3 | Mapped | |
| 13 | Appliance3 | Mapped | Documented appliance change on 25 March 2015; possible signature/mapping drift |
| 15 | Appliance3 | Mapped | |
| 16 | Appliance5 | Mapped | |
| 17 | Appliance4 | Mapped | |
| 18 | Appliance5 | Mapped | |
| 19 | Appliance2 | Mapped | |
| 20 | Appliance4 | Mapped | |
| 21 | Appliance3 | Mapped | |

The mapping file marks these selected channels as identified. This does not guarantee that every timestamp is complete or that the appliance signature is stable throughout the entire household record. House 13's documented appliance change is a particular concern and should be considered when interpreting its results.

House 12 and House 14 are absent from the supplied cleaned files used by this project. They are not included in the EDA or NILM results. The current project therefore analyses 19 households.

## Remaining data concerns and interpretation

- Missing intervals and official zero-filled periods can bias off-time, active-minute fractions and cycle counts.
- One-minute averaging hides sub-minute switching behaviour and smooths short power peaks.
- Appliance labels may be incomplete, household-specific or change over time.
- Appliance-level channels do not necessarily sum to aggregate consumption; aggregate readings may include unmetered loads and measurement inconsistencies.
- Washing-machine events are identified using a heuristic (at least 10 W, bridging inactive gaps up to 2 minutes, retaining events of at least 5 minutes). They should not automatically be interpreted as complete manufacturer-defined wash programmes.
- The REFIT sample contains UK households and should not be assumed to represent Indian households, appliances, electrical conditions or usage patterns.
- The current one-minute pipeline and NILM model are exploratory. A deployment dataset would need locally validated appliance mappings, outage/quality flags and representative household coverage.

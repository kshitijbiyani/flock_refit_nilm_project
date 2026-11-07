# Recommendation – Utility-facing summary

## Executive recommendation

Treat this REFIT washing-machine disaggregation work as a **research prototype**, not a customer-facing operational service. The analysis demonstrates a reproducible workflow for cleaning aggregate meter data, profiling mapped washing-machine channels and estimating minute-level washer power. However, the current model is not sufficiently reliable for definitive cycle detection, household-level advice, billing, or savings claims.

A limited, instrumented pilot may be worthwhile after the model is improved and tested against locally collected appliance-meter data.

## What the analysis shows

- The EDA used official cleaned REFIT data for **19 households** with a mapped washing-machine channel. Households 12 and 14 were not present in the supplied cleaned dataset.
- Across the combined household timelines, washer-channel coverage was **86.39%**. Missing intervals and zero-filled periods mean that a zero reading cannot always be interpreted as confirmed non-use.
- The event heuristic (at least 10 W, bridging inactive gaps up to 2 minutes, and retaining events of at least 5 minutes) identified **9,998 candidate events**. These are analytical events, not verified complete wash cycles.
- Candidate event duration had a median of **45 minutes**. The long tail includes events that are unlikely to represent one ordinary wash cycle, so event boundaries need further validation.
- On the held-out test data, the model achieved **9.30 W MAE**, **85.52 W RMSE** and **R² = 0.203**. It underestimated total washer energy by **8.87%**.
- Active-minute detection was weak: **13.7% precision**, **43.3% recall** and **0.208 F1**. In practical terms, many predicted active minutes were false positives and the model missed more than half of actual active minutes.

The relatively low MAE should not be interpreted in isolation: the data contain many inactive minutes, while the higher RMSE and weak active-minute scores show that the model does not yet reconstruct washer operation reliably.

## One energy-saving opportunity to test

Test a customer education intervention that encourages households to **consolidate compatible laundry loads and consider an appropriate eco programme**, where this is suitable for the household, fabric and hygiene requirements.

This is a **pilot hypothesis, not a finding established by the REFIT analysis**. The available data do not identify drum fill level, load size, programme selection or whether a particular cycle could safely be consolidated. NILM estimates alone must not be used to tell a customer that a load was inefficient or that a specific amount of energy could have been saved.

A utility could first use customer research to identify households interested in this advice, then offer a voluntary prompt or guidance. Evaluate the intervention using temporary appliance submeters or another independently validated measurement method.

### How to measure the pilot

- Compare washing-machine kWh per completed cycle and total weekly washing-machine kWh before and after the intervention.
- Use a randomized or matched comparison group where practical.
- Record cycle counts and, with consent, relevant context such as household occupancy or season; collect only what is necessary.
- Report sample size, uncertainty and changes in household behaviour.
- Do not calculate savings solely from this model's predicted energy. Validate a sample of predicted events and energy against appliance submeters.

## Applicability to India

REFIT represents a small set of UK homes in Loughborough, not a representative Indian household sample. Appliance ownership and types, washing-machine technology, voltage, household size, climate, usage patterns and meter infrastructure may differ. The current model should **not** be transferred to Indian customers without local labelled aggregate-plus-appliance data, local validation and calibration across household types and seasons.

## Effect of 15- and 30-minute meter data

The model was developed and evaluated at **1-minute resolution**. Coarser 15- or 30-minute readings may preserve approximate energy totals over longer periods, but they smooth peaks and can hide short operating phases. This is likely to make cycle start/end detection and separation of overlapping appliance loads more difficult. No 15- or 30-minute experiment was run in this analysis; performance at those intervals is therefore unknown and must be tested separately.

## What is needed before deployment

1. Collect representative Indian household aggregate and appliance-submeter data across regions and seasons.
2. Record appliance make/model, rated power and, where feasible, programme and load-size metadata.
3. Preserve explicit outage and missingness indicators; do not treat zero-filled gaps as confirmed appliance-off periods.
4. Validate event detection and energy estimates against appliance submeters, using household-separated and time-aware evaluation.
5. Improve active-state detection and assess simple baselines and alternative model designs before operational use.
6. Monitor performance by household type and over time, including drift, data outages and changes to appliance channels.
7. Obtain appropriate customer consent and minimize any contextual data collected.

## Deployment recommendation

Proceed only with a **small, prospective validation pilot**, not a production rollout. Temporarily submeter washing machines in a representative sample, compare NILM estimates with measured appliance power and energy, and assess event-level errors as well as total-energy error. Set explicit acceptance thresholds before the pilot begins. Only consider a customer-facing energy-saving intervention after the model demonstrates adequate local performance and the intervention's savings are independently measured.

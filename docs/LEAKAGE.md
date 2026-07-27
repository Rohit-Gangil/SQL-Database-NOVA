# Leakage and Splitting

The most common way a portfolio forecasting project reports numbers it has not earned
is by leaking future information into features. This document states exactly what
NOVA does to prevent it, and how that prevention is tested rather than asserted.

## Splitting

**There is no random splitting anywhere in this repository.** Series-days are ordered
in time; a random split lets the model see Wednesday while predicting Tuesday and
inflates every metric.

| | |
|---|---|
| Training | everything strictly before the origin |
| Backtest origins | 6, monthly, 2025-07-01 → 2025-12-01 |
| Horizon | 14 days |
| Scheme | rolling origin — the model is refit at each origin |

Six origins rather than one because a single split cannot say whether a difference
between two models is real. All confidence intervals come from variation across
origins.

## Availability lag

A feature computed for date *T* may only read records with `date_key ≤ T − LAG`,
where `LAG = SPLIT.feature_lag_days = 1`. Yesterday's sales are not in the warehouse
at 00:00 today. Writing `lag(1)` when true availability is `lag(2)` is invisible in
a backtest and destroys the model in production.

Concretely, in `nova/features/build.py`:

- lag features use `LAG(target, d + LAG)` for `d ∈ {1,2,3,7,14,28}`
- rolling windows use `ROWS BETWEEN (w + LAG − 1) PRECEDING AND LAG PRECEDING`
- **no window ever includes `CURRENT ROW`** for a target-derived feature

Calendar features (day of week, day-of-year harmonics) are exempt: they are
deterministic functions of the date, so a model may legitimately know that next
Tuesday is a Tuesday. Static product and branch attributes are likewise known in
advance.

## The test that decides whether any of this is true

`tests/test_leakage.py::test_features_before_cutoff_are_invariant_to_future`

1. Build features on clean data.
2. Multiply every target value on or after a cutoff by 1000.
3. Rebuild features using **the same production `feature_sql()`**.
4. Assert every target-derived feature value *before* the cutoff is unchanged.

Any feature reaching forward in time moves, and the test fails.

An invariance test alone is not sufficient — features that were all NULL would also
pass — so `test_perturbation_is_actually_detectable` proves the instrument works by
showing the same perturbation *does* move rows after the cutoff.

### It caught a real leak

The first run failed:

```
AssertionError: features leak future information:
  region_lag (482 rows differ), national_lag (2078 rows differ)
```

The hierarchy features aggregated demand to `(region, drug, date)` and then applied
`LAG()` **after joining back to branch-level rows**. That partition contains one row
per branch per date, so `LAG(x, 1)` returned an arbitrary sibling branch's row from
the *same date* rather than the previous date — leaking today's regional demand into
today's features.

The fix applies the lag inside the aggregate CTE, at the grain where each date
appears exactly once. This is the class of bug that is essentially invisible by
inspection and would have inflated every downstream metric.

## Censoring is not leakage, but it is the mirror image

Leakage is using information you would not have. Censoring is *failing to use*
information you do have, and it biases in the opposite direction.

`units_sold` under-reports demand on stockout days. A model trained on it learns
that stockout days had low demand, forecasts lower, and causes the next stockout.
`units_demanded_censored = sold + recorded unmet` adds back what the counter saw.

Neither equals true demand — some patients leave without asking — so the correction
is partial. P6 reports both models (`lightgbm` and `lightgbm_sales_only`) as an
ablation rather than assuming the correction helps.

## Ground truth is physically unreachable

Simulator truth lives in the `nova_truth` schema, not in `mart`. In the PostgreSQL
layer it is a separate schema with grants withheld from every application role; in
DuckDB it is a separate schema that no feature query references.

`nova/warehouse/build.py` includes a standing data-quality check that fails the
build if any column matching `%_true%` or `mu_%` appears in the `mart` schema.
Physical separation beats discipline, because the failure mode — a label leaking
into a feature and producing a meaningless 0.99 AUC — is silent.

## Remaining limitations

- **Dispersion for prediction intervals is estimated on backtest residuals**, which
  are held out relative to training but reused across origins. A fully clean
  protocol would estimate it on a separate calibration window.
- **The `USING SAMPLE` reservoir sample** for training rows is seeded and drawn from
  pre-origin data only, so it cannot leak, but it does mean the model sees ~1.5M of
  the available rows rather than all of them.
- **Independence across days** is assumed when summing daily distributions to a
  horizon distribution. Real demand is autocorrelated, so intervals are slightly
  too narrow.

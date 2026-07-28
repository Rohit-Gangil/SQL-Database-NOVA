# Progress Log

One entry per phase: what was built, what was measured, what was deferred.
Numbers here are reproducible by a `make` target in this repository.

---

## P0 — Problem definition ✅

**Built.** `docs/00-PROBLEM.md` — problem statement, sourced evidence, customer,
business metrics, non-goals, theme decision. `docs/DECISIONS.md`. `.gitignore`.

**Decided.** No re-theme (D-001). Framing changed from "a pharmacy database" to
"a replenishment decision system."

---

## P1 — Phase plan ✅

**Built.** `docs/PLAN.md` — 12 phases with deliverables, rejected alternatives, and
objectively checkable Definitions of Done. Critical path declared as P2→P6, with
P7–P11 designated deferrable *before* the flagship is compromised.

---

## P2 — OLTP hardening ✅ (written) / ⚠️ UNVERIFIED (execution)

**Built.** PostgreSQL port of the Oracle schema: `db/ddl/`, `db/functions/`,
`db/indexes/`, `db/policies/`, `docker-compose.yml`, `docs/PII-POLICY.md`.
Original Oracle scripts preserved unmodified in `legacy/`.

**The structural fix.** The original `Stock` table (legacy:103-108) was keyed only by
pharmacy with inventory stored as a `VARCHAR2`. No drug column, no date column, no
numeric quantity — it could not answer the one question the project depends on.
Replaced by `inventory_lot`, `inventory_snapshot` (CHECK-enforced flow identity), and
`replenishment_order`. Added a `dispense` table, absent from the original, which
records unmet demand.

**Systematic procedure changes.** No `COMMIT` in callees; exceptions raise instead of
printing to `DBMS_OUTPUT` and returning success; existence checks moved from
procedural `SELECT COUNT(*)` to declarative foreign keys; reports return sets.

**PII.** Aadhaar removed as primary key and from plaintext storage; surrogate keys,
salted SHA-256, de-identified views, RLS, read-only `nova_llm` role.

**NOT MEASURED.** No Docker or `psql` on the build machine (D-005). The Postgres path
has never been executed. **No `EXPLAIN ANALYZE` numbers are reported**, because none
were taken. This is stated in the README rather than papered over.

---

## P3 — Data simulator ✅

**Built.** `nova/simulator/` — entities, demand DGP, incumbent inventory policy,
anomaly injection. `docs/SIMULATOR.md`.

**Measured.**

| | |
|---|---|
| Rows in `fact_demand` | **5,918,400** |
| Zero-sales cells | **74.4%** (DoD band [0.65, 0.90]) |
| Series classified "lumpy" | **94.0%** (Syntetos–Boylan) |
| Series-days with unmet demand | **1.60%** |
| Incumbent fill rate | **92.3%** |
| Incumbent expiry waste | **1.51%** of units received |
| Runtime | ~88s |

**Two bugs found and fixed during baseline calibration**, both of which had been
flattering the setup:

1. **Opening stock destroyed on first delivery.** Initial inventory was seeded into
   the same cohort slot the first arrival lands in, and the receipt path overwrites a
   slot rather than adding to it. Made the fill-rate curve non-monotonic.
2. **Stock arrived with full shelf life.** Real distributors ship with 40–80% already
   consumed. Modelling receipt as fresh understated expiry waste by more than an order
   of magnitude (0.08% vs an industry norm of 2–3%), making the over-stock arm of the
   newsvendor trade-off effectively free.

**A third bug caught by the tests.** The ledger flow identity failed on **142,605
rows** because the opening position was recorded *after* receipts, double-counting
arrivals. Now asserted on every row.

**Baseline calibrated, not guessed.** Safety factor swept until the incumbent operated
where real chains do. Beating an incompetent baseline proves nothing.

**Tests.** 12 passing, including reproducibility, intermittency band, overdispersion,
seasonal-amplitude recovery correlated with configuration, and the flow identity.

---

## P4 — Warehouse ✅

**Built.** `nova/warehouse/models.sql` (star schema, hierarchy rollups, Syntetos–Boylan
classification) and `build.py` with 11 data-quality checks.

**Measured.** All 11 checks pass, including branch→region→national rollup
reconciliation and a standing leakage guard that fails the build if any `%_true%`
column reaches the `mart` schema.

| Table | Rows |
|---|---:|
| `fct_demand_daily` | 5,918,400 |
| `fct_demand_region` | 986,400 |
| `fct_demand_national` | 197,280 |
| `dim_series` | 5,400 |

**Deferred.** dbt (D-008) and Dagster — ordered SQL achieves the same DAG without a
second configuration surface.

---

## P5 — Point-in-time features ✅

**Built.** `nova/features/build.py` — 34 features across 7 groups, every window
offset by the availability lag. `docs/LEAKAGE.md`. `tests/test_leakage.py`.

**It caught a real leak in my own code.** Hierarchy features aggregated to
`(region, drug, date)` and then applied `LAG()` *after* joining back to branch-level
rows. That partition holds one row per branch per date, so `LAG(1)` returned a sibling
branch's **same-day** total — leaking today's regional demand into today's features.
**482 `region_lag` rows and 2,078 `national_lag` rows.** Fixed by lagging inside the
aggregate CTE where each date appears exactly once.

This is the class of bug that is invisible by inspection and would have inflated every
downstream number.

**Also fixed.** DuckDB date subtraction yields `INTERVAL`, arriving in pandas as
`timedelta64` and failing inside LightGBM with a `DTypePromotionError` naming no
column. Cast via `DATE_DIFF`, plus a dtype guard in `fit_gbm` that names the offender.

**Tests.** 5 passing, including the future-perturbation invariance test and a
companion proving the perturbation is detectable (so an all-NULL feature set cannot
pass trivially).

---

## P12 — Engineering hygiene ✅

**Built.** Pinned `pyproject.toml`, ruff config, pytest config, `Makefile`,
`.gitattributes`, GitHub Actions running lint + tests + a cold-clone pipeline smoke
test with `--strict` data-quality enforcement.

**Measured.** 36 tests passing locally.

---

## P6 — Forecasting ladder and decision layer ✅

**Built.** `nova/forecast/` (baselines, metrics, LightGBM, rolling-origin backtest),
`nova/inventory/` (newsvendor policy, continuous policy comparison, sensitivity),
`nova/report/results.py`. Full table in `docs/RESULTS.md`, generated from artifacts.

**Measured.** 6 rolling origins, 14-day horizon, scored against true demand.
Backtest runtime 1,223s.

| Model | WAPE | Bias |
|---|---:|---:|
| Seasonal naive | 1.1229 | +0.017 |
| Trailing 28-day mean (best classical) | 0.9071 | +0.017 |
| SBA | 0.9432 | +0.028 |
| TSB | 0.9110 | +0.022 |
| LightGBM (censoring-corrected) | **0.8928** | −0.015 |
| _Oracle floor_ | _0.8827_ | _+0.006_ |

**Policy comparison**, continuous 184-day window, monthly refresh:
total cost ₹2,080,639 → ₹401,010 (**−80.7%**, 95% CI −82.6% to −79.1%);
fill rate 97.74% → 99.74%; units unmet 17,410 → 2,041.

**Three findings worth stating plainly:**

1. **The forecasting gain is small (1.6%) and should be.** Only 0.024 WAPE of
   reducible error existed between the best classical method and the oracle floor.
   A large claimed win here would be suspect.
2. **The censoring correction made WAPE worse**, 0.8928 vs 0.8854, while cutting bias
   4× (−0.062 → −0.015). I expected it to improve both. It did not, and the table
   says so. Bias is the right criterion for a system whose output is an order
   quantity.
3. **The headline −80.7% is assumption-dependent.** Swept across a 16× range of the
   stockout penalty it moves between −54% and −90%. Direction and mechanism are
   robust; the specific percentage is not, and RESULTS.md states this.

**Two evaluation bugs found and fixed:**

1. A **14-day evaluation window made expiry structurally impossible** (effective
   shelf lives start at 72 days), so `waste_cost` was identically zero for both
   policies and over-ordering was free. The first comparison returned −79% for that
   reason. Fixed by stitching the origins into a continuous 184-day simulation.
2. The **incumbent baseline was leaking** — its reorder point used a mean over the
   whole period including the future, lifting its fill rate from 92.3% to 98.9% and
   making it a different policy from the one under comparison.

**Not built.** Rung 3 (TFT / N-BEATS) — no GPU, torch out of scope (D-006).
Hierarchical reconciliation (MinT/OLS) was planned in P1 and **not implemented**;
the hierarchy rollups and coherence checks exist in the warehouse, but forecasts are
produced at the series level only and are not reconciled.

---

## P7–P11 — DEFERRED (D-006)

Not built: GNN anomaly detection, causal inference/uplift, FastAPI+ONNX serving,
drift monitoring, text-to-SQL eval harness. Rung 3 of the model ladder (TFT/N-BEATS)
also not built — no GPU, torch out of scope this pass.

The plan (P1) declared these deferrable before the flagship is compromised, and that
rule was followed rather than quietly abandoned. Ground truth for the anomaly,
drift and causal phases **is** generated and sits in `nova_truth`, so those phases
start from a working evaluation harness rather than from zero.

**No numbers are claimed for any deferred phase.**

---

## Audit pass — self-review, fixes, and a hostable site (2026-07-28)

**Built.** `docs/AUDIT.md` (2 critical, 6 major, 5 minor), `docs/FIX-PLAN.md`,
`nova/inventory/lots.py`, `nova/report/build_site.py`, `docs/site/index.html`,
`tests/test_baselines_vectorised.py`.

**Fixed.**

| Item | Outcome |
|---|---|
| C-1 policy expiry ~200× too cheap | Fixed with lot-cohort FEFO. **Headline moved only −80.73% → −81.27%** |
| C-2 unmeasured coverage claim | Coverage, interval width and pinball now computed and reported |
| M-1 two policy simulators | Collapsed to one; tests now exercise the shipped path |
| M-2 dispersion on eval window | Moved to a 28-day calibration window between train and eval |
| M-3 CI vs sensitivity framing | Both labelled; sweep given equal prominence |
| M-5 artifacts unverifiable | Small CSV/JSON committed |
| m-1, m-2, m-4 | Pins corrected, reshape guarded, dead variable removed |
| m-3 vectorise baselines | Done, with 8 equivalence tests — **but runtime rose 1,223s → 2,048s** |
| m-5 no UI | Static self-contained dashboard, GitHub Pages ready |

**Three things went against expectation, and all three are published as such:**

1. **Fixing C-1 barely moved the headline.** I predicted the saving would shrink
   substantially. Waste is a rounding-error line item under both policies
   (₹5.4k vs ₹1.90M stockout cost), so a ~200× correction to it changed 0.5pp.
   The conclusion survived a correction it did not need.
2. **Interval coverage came back too WIDE, not too narrow.** Nominal 90% measured
   0.977. Estimated dispersion (k≈1.29) sits below the generating 1.6 because
   model error inflates the residuals the estimator sees. Consequence: the
   newsvendor over-orders at high critical ratios, so the reported saving is
   conservative on that axis.
3. **Vectorising the baselines did not speed up the backtest.** The diagnosis was
   wrong — LightGBM and the 5.9M-row feature queries are the bottleneck, and the
   C-2 fix added a second prediction window per model per origin.

**New finding raised during the fix (C-1b).** The comparison's incumbent is a
*leaner policy* than the simulator's: it lacks pack-size rounding and the
minimum-stocking rule, so it expires ~160 units where the simulator expires
~13,400. Documented as a limitation in RESULTS.md rather than changed, because
altering the baseline policy now would invalidate the comparison.

**NOT MET.** `docs/PLAN.md` P6 DoD item 6 — the leave-one-group-out feature
ablation was never run. `FEATURE_GROUPS` scaffolding has been deleted rather than
left implying almost-finished work. P6 DoD item 4 (hierarchical reconciliation)
also remains unmet, as previously disclosed.

**Measured.** 47 tests pass, ruff clean, cold clone verified end to end.

# Audit

Full review of the repository against its own claims. Severity is judged by one
question: **does this make a reported number wrong, or make a documented claim
untrue?** Cosmetic issues rank below both.

Audit date: 2026-07-28. Commit: `feature/nova-ml-platform` @ 9 commits.

**Summary: 2 critical, 6 major, 5 minor.** The headline forecast numbers survive.
The headline **cost** number does not survive unchanged — C-1 biases it upward by
an amount that must be re-measured, not estimated.

---

## CRITICAL

### C-1 — The policy comparison's expiry model understates waste by ~200×

**Where:** `nova/inventory/compare.py:109-123` (`simulate_continuous`)

**What.** The comparison tracks a *single volume-weighted average age* per series:

```python
age = np.where(total > 0, (age * on_hand) / np.maximum(total, 1e-9), 0.0)
age += 1.0
too_old = age > effective_shelf
```

Every arrival drags that average back toward zero, so `age > effective_shelf`
almost never fires, and when it does it expires the *entire* holding at once
rather than the oldest cohort. The simulator (`nova/simulator/inventory.py`) does
the correct thing: per-lot cohorts consumed first-expiry-first-out.

**Measured, over the identical 2025-07-01 → 2025-12-31 window:**

| | Units expired |
|---|---:|
| Simulator (lot-level FEFO) | **13,384** (1.75% of 763,754 units received) |
| Policy comparison (average-age) | **68** (incumbent) / 109 (newsvendor) |

**Why it matters — this is the important one.** Waste is the overage arm of the
newsvendor trade-off. Making it ~200× too cheap makes over-ordering nearly free,
and the newsvendor policy is precisely the one that orders more (it holds +36%
inventory). **The reported −80.7% is therefore biased in NOVA's favour by an
unknown amount.** Waste is 0.13% of total cost in the comparison; in a
lot-accurate model it would be materially larger.

This is the same class of error as the 14-day-window bug fixed earlier in P6 —
that one made waste *exactly* zero, this one makes it *nearly* zero. The first was
caught; this one was not, because a small non-zero number looks like it is working.

**Fix.** Port the cohort/FEFO logic from `nova/simulator/inventory.py` into the
policy simulator so both use one lot-level implementation. Re-run and report
whatever number comes out, including if the saving shrinks substantially.

### C-2 — `RESULTS.md` and `DECISIONS.md` claim metrics that are never computed

**Where:** `docs/RESULTS.md:92`, `docs/DECISIONS.md:85`, against
`nova/forecast/backtest.py:132-142` (`evaluate`)

**What.** Both documents state that the negative-binomial distributional
assumption "is tested rather than asserted — interval coverage is reported in
`artifacts/backtest_per_origin.csv`". **No coverage column exists.** No pinball
loss either. `metrics.coverage` and `metrics.pinball_loss` are implemented and
unit-tested, but `evaluate()` computes only `wape`, `bias`, `rmse`, `rmsse`.

`docs/00-PROBLEM.md:110` also lists "pinball loss and calibration coverage" as
reported metrics.

**Why it matters.** The entire pitch of this repository is *every number is
measured*. An unmeasured claim in the results document is worse here than
anywhere else, because the document's credibility is the product.

**Fix.** Compute both. `artifacts/gbm_preds.npy` and `artifacts/truth.npy` are
already saved, so coverage and pinball can be computed **without a 20-minute
backtest rerun**. If for any reason they cannot be computed, delete the claim from
all three documents rather than soften it.

---

## MAJOR

### M-1 — Two divergent policy simulators; the tested path is not the shipped path

**Where:** `nova/inventory/newsvendor.py:151` (`simulate_policy_cost`) vs
`nova/inventory/compare.py:79` (`simulate_continuous`)

`simulate_policy_cost` is referenced only by `tests/test_forecast.py`. The
headline number comes from `simulate_continuous`, which has **no direct test**.
The U-shaped-cost test — the one asserting that both starvation and glut cost more
than a sensible middle, which is the core economic property — validates code that
does not ship.

**Fix.** Collapse to one implementation (the lot-level one from C-1) and point the
existing tests at it.

### M-2 — Predictive-interval dispersion is estimated on the evaluation window

**Where:** `nova/forecast/backtest.py:181-183`

```python
dispersion_samples.append(gbm.estimate_dispersion(actual.ravel(), gbm_pred.ravel()))
```

`actual` is the held-out *evaluation* window. So `k` is calibrated on exactly the
data the intervals are then judged against. `docs/LEAKAGE.md` describes it as
"estimated from held-out residuals" — true relative to *training*, misleading
relative to *evaluation*.

**Why it matters.** Any coverage figure produced under C-2's fix would be
optimistic. Since C-2 introduces coverage reporting, this must be fixed in the
same change or the new number is born compromised.

**Fix.** Estimate `k` on a calibration window strictly between train end and the
origin, and state the change.

### M-3 — A ±1.8pp confidence interval is reported beside a 36pp parameter sensitivity

**Where:** `nova/inventory/compare.py:218-228`, surfaced in `docs/RESULTS.md`

The bootstrap CI is `[−82.60%, −79.05%]` — a 3.5-point span — while the
sensitivity sweep over the stockout penalty moves the same quantity from −54% to
−90%. The CI captures only *SKU sampling* variation; it excludes forecast error,
model uncertainty, and the cost assumptions that dominate. Presenting a tight CI
prominently implies a precision the analysis does not have.

**Fix.** Keep the CI but label what it does and does not cover, and give the
sensitivity range equal or greater prominence in every summary — README, site, and
RESULTS.md.

### M-4 — The feature ablation was specified, scaffolded, and never run

**Where:** `nova/features/build.py:186-199` (`FEATURE_GROUPS`), unused anywhere.
Required by `docs/PLAN.md:217` (P6 DoD item 6).

`FEATURE_GROUPS` is dead code carrying the intent of an ablation that does not
exist. `docs/LEAKAGE.md:87` says the censoring question is settled "as an ablation
rather than assuming" — that one *was* done (the sales-only model), so the claim
is defensible, but the feature-group ablation is simply missing.

**Fix.** Run a leave-one-group-out ablation using the saved artifacts where
possible, or delete `FEATURE_GROUPS` and strike the P6 DoD item as not met.
Do not leave scaffolding implying work that was not done.

### M-5 — `artifacts/` is gitignored, so no reported number is verifiable from a clone

**Where:** `.gitignore:45`

`docs/RESULTS.md` states "Every number below comes from `artifacts/`". Those files
are not in the repository. A reviewer cloning the repo must run the full 25-minute
pipeline before they can check anything — and the planned static site cannot be
built at all without them.

Sizes make this trivial to fix: `backtest_per_origin.csv` 4.8 KB,
`policy_*.csv/json` < 1 KB each, `dispersion.txt` 18 B. Only `gbm_preds.npy` and
`truth.npy` (1.8 MB each) and `dim.parquet` (28 KB) are large-ish.

**Fix.** Commit the small CSV/JSON/txt artifacts; keep `.npy` ignored.

### M-6 — Hierarchical reconciliation: planned, not built

**Where:** `docs/PLAN.md:197` specifies MinT/OLS reconciliation as P6 DoD item 4
("child forecasts sum to parent", asserted in a test). Not implemented.

**Status: already disclosed** in `README.md:182` and `docs/PROGRESS.md:194`, so
this is not a live overclaim. It is recorded here because it remains the largest
functional gap against the stated plan, and because `docs/PLAN.md:21` still shows
"model ladder + reconciliation" in the architecture without qualification.

**Fix.** Either implement OLS reconciliation (the cheap variant — the rollup tables
already exist in `mart`) or annotate PLAN.md so no document implies it shipped.

---

## MINOR

### m-1 — Two dependency pins do not match the versions actually used

`pyproject.toml` pins `pytest==9.0.1` and `ruff==0.14.6`; installed and used were
`9.1.1` and `0.16.0`. The file's own comment says the pins are "the versions this
project was actually built and measured on" — untrue for these two. Runtime
dependencies all match correctly.

### m-2 — `reshape()` assumes a complete rectangular panel without asserting it

`nova/forecast/backtest.py:68,69,128,200`. Each relies on `ORDER BY` plus an exact
row count. A data-quality check for date gaps exists, so the risk is low, but a
silent misalignment is possible if two defects cancel in the row count. Cheap to
guard with an explicit shape assertion.

### m-3 — The backtest takes ~20 minutes, dominated by a Python loop

`nova/forecast/backtest.py:85-98` loops 5,400 series × 6 origins in pure Python for
the classical baselines. This is the main obstacle to iterating on anything
downstream, and it makes the C-1 fix expensive to validate.

### m-4 — Dead variable

`nova/forecast/backtest.py:158,171`: `naive_preds_by_origin` is populated and never
read.

### m-5 — No user interface

There is no way to see any of this without cloning and running a 25-minute
pipeline. For a portfolio artefact this is the largest practical gap. Addressed in
Stage 3.

---

## Verified as sound (checked, no action)

- **Cold-clone reproducibility.** Cloned to a fresh directory: `simulate --small`
  → `warehouse --strict` (11/11 checks pass) → `features` (54,750 rows) → `pytest`
  (36 pass). No missing files, no hidden state.
- **Ledger flow identity** holds on all 5,918,400 rows.
- **Leakage tests** pass, including future-perturbation invariance and its
  detectability companion.
- **No secrets** in tracked source. The only credential-shaped strings are
  docker-compose environment defaults and the documented dev-only PII salt.
- **No real PII.** All data synthetic; ground truth physically separated in
  `nova_truth` with a standing data-quality check against truth columns reaching
  `mart`.
- **Runtime dependency pins** all match what was used.
- **`main` is untouched** and identical to `origin/main`.

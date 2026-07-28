# Fix Plan

Ordered by severity. Each entry: the fix, files touched, verification, risk.

**Sequencing note.** `m-3` (vectorise the baselines) is scheduled *first* despite
being minor, because the backtest currently costs ~20 minutes and both `C-2` and
`M-2` require a rerun. Making the rerun cheap first makes everything after it
cheaper. This is the only place where a minor item jumps the queue, and the reason
is throughput, not importance.

---

## Order of work

| # | Item | Why here |
|---|---|---|
| 1 | m-3 vectorise baselines | Unblocks cheap reruns for everything below |
| 2 | C-2 + M-2 compute coverage/pinball, fix dispersion window | One backtest rerun serves both |
| 3 | C-1 + M-1 lot-level policy simulator, unified | The headline number depends on it |
| 4 | M-5 commit small artifacts | Required by the site and by verifiability |
| 5 | M-3 presentation of CI vs sensitivity | Documentation only |
| 6 | M-4 ablation: run or remove | Decide once numbers are stable |
| 7 | m-1, m-2, m-4 | Cheap cleanups |
| 8 | M-6 reconciliation | Largest scope; decide last against remaining budget |

---

### 1. m-3 — Vectorise the classical baselines
**Fix.** Replace the per-series Python loop in `run_baselines` with array
operations. Naive/seasonal-naive/mean are trivially vectorisable. Croston/SBA/TSB
are recursive over time but can be vectorised *across series*: run the recursion
once over the time axis with all 5,400 series as a vector.
**Files.** `nova/forecast/baselines.py`, `nova/forecast/backtest.py`.
**Verify.** New vectorised output must match the current per-series
implementation to within floating-point tolerance on a small fixture — this is a
regression test, added before the change is trusted.
**Risk.** Medium. Recursion order is easy to get subtly wrong. Mitigated entirely
by the equivalence test against the existing, already-validated implementation.

### 2. C-2 + M-2 — Coverage and pinball; dispersion on a proper calibration window
**Fix.** Add `coverage_80`, `coverage_90` and `pinball_50/90` to `evaluate()`.
Estimate the negative-binomial `k` on a **calibration window** — the 28 days
immediately before each origin, which is held out from training and disjoint from
evaluation — instead of on the evaluation window itself.
**Files.** `nova/forecast/backtest.py`, `nova/forecast/gbm.py`,
`docs/RESULTS.md` (generated), `docs/LEAKAGE.md`, `docs/DECISIONS.md`.
**Verify.** Coverage columns exist in `artifacts/backtest_per_origin.csv`;
RESULTS.md reports them; the claim and the artifact now agree.
**Risk.** Low mechanically. **The reported coverage may be poor** — the
independence-across-days assumption should make intervals too narrow. If it is
poor, that gets reported as a finding, not tuned away.

### 3. C-1 + M-1 — One lot-level policy simulator
**Fix.** Move the cohort/FEFO logic out of `nova/simulator/inventory.py` into a
shared module and use it for both the incumbent and the newsvendor policy.
Delete `newsvendor.simulate_policy_cost`; point its tests at the surviving
implementation.
**Files.** new `nova/inventory/lots.py`, `nova/inventory/compare.py`,
`nova/inventory/newsvendor.py`, `tests/test_forecast.py`.
**Verify.** Expiry over the 184-day window must land in the same order of
magnitude as the simulator's 13,384 units, not 68. The U-shaped cost test must
pass against the *shipped* path.
**Risk.** **High, and this is the expected outcome:** waste becomes materially
more expensive, so the newsvendor's advantage should shrink. Whatever number
results is what gets published, including if −80.7% becomes something far less
impressive. No LightGBM retrain needed — `artifacts/gbm_preds.npy` is saved, so
this rerun is fast.

### 4. M-5 — Commit small artifacts
**Fix.** Un-ignore `artifacts/*.csv`, `*.json`, `*.txt`; keep `*.npy` ignored.
**Files.** `.gitignore`.
**Risk.** None. Total added < 10 KB.

### 5. M-3 — Honest presentation of uncertainty
**Fix.** Label the bootstrap CI with what it covers (SKU sampling only) and what
it excludes (forecast error, model choice, cost assumptions). Give the sensitivity
range at least equal prominence everywhere the headline appears.
**Files.** `nova/report/results.py`, `README.md`, site.
**Risk.** None.

### 6. M-4 — Feature ablation: run it or delete the scaffolding
**Fix.** Preferred: leave-one-group-out ablation at a single origin (six extra
LightGBM fits — affordable once m-3 lands). Fallback if budget is gone: delete
`FEATURE_GROUPS` and record the P6 DoD item as **not met** in PROGRESS.md.
**Risk.** Low. The honest fallback is acceptable; silent scaffolding is not.

### 7. m-1, m-2, m-4 — Cleanups
Correct the two dependency pins and the false comment; add shape assertions
around the four `reshape()` calls; delete `naive_preds_by_origin`.
**Risk.** None.

### 8. M-6 — Hierarchical reconciliation
**Fix.** OLS reconciliation across (branch,drug) → (region,drug) →
(national,drug), with a coherence test asserting children sum to parents.
**Decision:** attempt only if items 1–7 are complete and verified. It is a genuine
feature addition, not a defect fix, and shipping a rushed reconciliation would be
worse than the current honest disclosure.

---

## Explicitly NOT fixing

| Item | Reason |
|---|---|
| PostgreSQL layer verification | No Docker or `psql` on this machine. Cannot be verified here at any effort level. Remains labelled UNVERIFIED everywhere, including on the new site. |
| Rung 3 (TFT / N-BEATS) | No GPU; torch is a ~2 GB install. Disclosed as not built. |
| P7–P11 | Out of scope for this pass; already disclosed. |
| Lead-time stochasticity | A simulator realism gap, documented in SIMULATOR.md. Changing it now would invalidate every existing number for a limitation that is already stated. |

---

## Definition of done for this pass

1. `docs/RESULTS.md` contains no claim not backed by a file in `artifacts/`.
2. One policy simulator, lot-level, exercised by the tests that assert its
   economics.
3. Coverage reported, whatever it says.
4. The site renders every number from `artifacts/`, with zero hardcoded figures.
5. `pytest` green, `ruff` clean, cold clone works.
6. Every number that moved is explained in PROGRESS.md, including numbers that
   moved against the project's own thesis.

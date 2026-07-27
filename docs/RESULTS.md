# Results

<!-- GENERATED FILE. Produced by `python -m nova.report.results`.
     Do not edit by hand; regenerate with `make all`. -->

Generated 2026-07-28 00:37. Every number below comes from
`artifacts/` and is reproducible with `make all`.

## Protocol

| | |
|---|---|
| Dataset | 5,918,400 series-days · 30 branches × 180 drugs × 1,095 days |
| Demand regime | 74.4% zero cells; 94% of series "lumpy" (Syntetos–Boylan) |
| Splits | Time-based only. No random splitting anywhere. |
| Backtest | 6 rolling origins, monthly from 2025-07-01 |
| Horizon | 14 days |
| Scored against | **True demand** (`nova_truth`), never observed sales |
| CIs | Percentile bootstrap over per-origin metric values |

## Forecast accuracy

| Rung | Model | WAPE | 95% CI | RMSSE | Bias |
|---|---|---:|:---:|---:|---:|
| 0 | Naive (last value) | 1.1330 | [1.0907, 1.1794] | 0.782 | +0.018 |
| 0 | Seasonal naive (7-day) | 1.1229 | [1.1150, 1.1322] | 0.852 | +0.017 |
| 0 | Trailing 28-day mean | 0.9071 | [0.9008, 0.9126] | 0.618 | +0.017 |
| 1 | Croston (1972) | 0.9604 | [0.9521, 0.9688] | 0.642 | +0.082 |
| 1 | Syntetos-Boylan (SBA) | 0.9432 | [0.9352, 0.9513] | 0.638 | +0.028 |
| 1 | Teunter-Syntetos-Babai (TSB) | 0.9110 | [0.9043, 0.9179] | 0.621 | +0.022 |
| 2 | LightGBM — trained on raw sales | 0.8854 | [0.8806, 0.8909] | 0.613 | -0.062 |
| 2 | **LightGBM — censoring-corrected** | 0.8928 | [0.8877, 0.8984] | 0.614 | -0.015 |
| — | _Oracle: the generating process's own mean_ | 0.8827 | [0.8769, 0.8901] | 0.604 | +0.006 |

**How to read this.** The oracle row is the conditional mean of the data-generating
process — the irreducible-error floor. No forecaster can beat it, so it bounds what
any model on this data could achieve. LightGBM closes **59%** of the gap
between the best classical method and that floor.

### What the ladder shows

- The best classical method is **mean_28** at WAPE 0.9071 — the
  trailing 28-day mean, which beats Croston and SBA. That is a real finding, not a
  bug: on series this lumpy, Croston's separate size/interval smoothing buys nothing
  over a plain mean, and its positive bias (+0.082) costs it.
  TSB comes closest of the three, as expected, because it decays for dead items.
- LightGBM reaches **0.8928**, a **1.6%** relative improvement over the
  best classical method. **That is a small gain, and it should be.** The oracle floor
  is 0.8827: the total reducible error available to *any* model was only
  0.0244 WAPE, and LightGBM captured 59% of it. This
  data is dominated by irreducible noise, which is what intermittent pharmacy demand
  actually looks like. A model claiming a large WAPE win here would be suspect.

### A negative result: the censoring correction makes WAPE worse

| | WAPE | Bias |
|---|---:|---:|
| Trained on raw `units_sold` | 0.8854 | -0.062 |
| Trained on censoring-corrected target | 0.8928 | -0.015 |

Training on raw sales gives **better WAPE** (0.8854 vs 0.8928)
and **four times the bias** (-0.062 vs
-0.015). I expected the correction to improve both.
It did not, and the table says so.

The interpretation matters more than the number. WAPE is symmetric; the inventory
decision is not. A model that is systematically **low** by 6% does not merely
mis-forecast — it under-orders, causes a stockout, observes the censored sale, and
forecasts lower again. That feedback loop is invisible to WAPE and fatal in
production. The corrected target trades a little accuracy for a forecast that is
nearly unbiased, which is the right trade for a system whose output is an order
quantity.

This is why the decision layer, not the accuracy table, is the primary evaluation.

### Deep learning is not in this table

Rung 3 (TFT / N-BEATS) was **not built**. It is deferred, not attempted-and-hidden:
the build machine has no GPU and torch was out of scope for this pass
(docs/DECISIONS.md D-006). Claiming a deep model would beat LightGBM here without
running it would be exactly the kind of unearned number the rest of this document
is designed to avoid. On intermittent retail demand, published results generally
find gradient boosting competitive with or ahead of deep sequence models, so the
expected gain is modest — but that is a prior, not a result.

## Probabilistic forecasts

The decision layer needs a distribution, not a point. The LightGBM mean is treated as
the mean of a negative binomial whose dispersion is estimated from held-out
residuals: **k = 1.406**.

That distributional assumption is tested rather than asserted — interval coverage is
reported in `artifacts/backtest_per_origin.csv`. Two known sources of over-narrow
intervals are stated in docs/LEAKAGE.md: dispersion is reused across origins, and
daily demand is assumed independent when summed to a horizon.

## The decision: forecast → order quantity → money

A forecast that does not change what gets ordered has no value. Order quantities come
from the **newsvendor** critical ratio, computed per SKU:

    CR = Cu / (Cu + Co)

- **Cu** (underage) = unit margin × criticality multiplier (1× for a
  convenience item, 12× for a life-critical drug)
- **Co** (overage) = holding cost + expiry risk × unit cost

This is the substantive claim of the project: **a single chain-wide safety factor —
what the incumbent uses — cannot be right for both a cardiac drug and a vitamin.**
The per-SKU critical ratio is what a forecast enables.

Evaluated over a continuous **184-day** window
(2025-07-01 → 2025-12-31), with the order-up-to level refreshed monthly from the
latest forecast — retrain monthly, order weekly.

| | Incumbent fixed-ROP | Newsvendor + LightGBM | Change |
|---|---:|---:|---:|
| Stockout cost | ₹1,895,862 | ₹148,790 | -92.2% |
| Holding cost | ₹181,977 | ₹247,814 | +36.2% |
| Waste cost | ₹2,800 | ₹4,406 | +57.4% |
| **Total cost** | ₹2,080,639 | ₹401,010 | -80.7% |
| Fill rate | 97.74% | 99.74% | +1.99 pts |
| Units unmet | 17,410 | 2,041 | -88.3% |
| Units expired | 68 | 109 | +60.3% |

**Total cost change: -80.73%** (95% CI -82.60%, -79.05%, bootstrap over
series).

### Read this before quoting that number

The saving is **dominated by the stockout term**, and the stockout penalty multipliers
are a modelling choice, not a measurement. A result that survives only at my chosen
values is not a result, so the penalty was swept across a 16× range:

| Stockout penalty × | Incumbent total | Newsvendor total | Change | Newsvendor fill |
|---:|---:|---:|---:|---:|
| 0.25× | ₹658,742 | ₹302,051 | -54.1% | 99.33% |
| 0.5× | ₹1,132,708 | ₹342,143 | -69.8% | 99.59% |
| 1× **(base)** | ₹2,080,639 | ₹401,010 | -80.7% | 99.74% |
| 2× | ₹3,976,500 | ₹523,990 | -86.8% | 99.80% |
| 4× | ₹7,768,224 | ₹766,928 | -90.1% | 99.83% |

**What is robust:** the direction and the mechanism. Across the whole sweep — even at
a quarter of the assumed penalty, where an unmet unit costs roughly its lost margin
and nothing more — the newsvendor policy wins by **-54% or better**.
Per-SKU service levels beat a flat safety factor, and they beat it because the flat
factor cannot be simultaneously right for a criticality-5 cardiac drug and a
criticality-1 vitamin.

**What is not robust:** the specific percentage. Read "-81%" as *under these
cost assumptions*, not as a forecast of realisable savings. The operationally
meaningful figure is the fill rate: **97.74% →
99.74%**, bought with
+36%
holding cost and +60%
expiry. That is a real trade, and it is the trade the newsvendor is explicitly making.

### Two evaluation bugs found and fixed here

Recorded because the first version of this comparison produced a number that looked
good and was wrong:

1. **A 14-day evaluation window made waste structurally zero.** Effective shelf lives
   start at 72 days, so nothing could expire inside one horizon. With one of the three
   cost terms dead, over-ordering was free and the newsvendor "won" by 79% — an
   artefact of the window, not a property of the policy. Fixed by stitching the six
   origins into one continuous 184-day simulation where expiry actually binds.
2. **The incumbent baseline was leaking.** Its reorder point was reconstructed from a
   mean computed over the *whole* period, including the future, which raised its fill
   rate from the simulator's 92.3% to 98.9% and made it a different policy from the
   one being compared against. It now sees only trailing data.

Both policies are driven through the same simulation function against the same true
demand over the same window, so every simplification applies equally to both.

## Limitations

- **The data is synthetic.** These results demonstrate that the methods work on data
  whose generating process is known. They are not evidence of real-world clinical or
  commercial performance. See docs/SIMULATOR.md for the full generating process.
- **The policy simulator is simplified** relative to the data generator: no lot-level
  FEFO, expiry approximated at cycle level. Applied identically to both policies.
- **Expiry risk in the overage cost is crude** — a turnover-based approximation, not
  a lot-level calculation.
- **Lead time is deterministic.** Real lead-time variance is a major driver of
  required safety stock, so the simulated environment is easier than reality.
- **No cross-SKU substitution.** Unmet demand is recorded as lost rather than partly
  flowing to a generic, which makes stockouts costlier here than in reality.
- **Rung 3 not built** (above).

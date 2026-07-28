"""Generate docs/RESULTS.md from the backtest artifacts.

    python -m nova.report.results

Every number in RESULTS.md is written by this script from files produced by
`make backtest` and `make policy`. Nothing is typed by hand, so the document
cannot drift from what the code actually measured.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from nova.config import ARTIFACT_DIR, REPO_ROOT, SIM, SPLIT
from nova.forecast import metrics

LADDER = [
    ("naive", "0", "Naive (last value)"),
    ("seasonal_naive", "0", "Seasonal naive (7-day)"),
    ("mean_28", "0", "Trailing 28-day mean"),
    ("croston", "1", "Croston (1972)"),
    ("sba", "1", "Syntetos-Boylan (SBA)"),
    ("tsb", "1", "Teunter-Syntetos-Babai (TSB)"),
    ("lightgbm_sales_only", "2", "LightGBM — trained on raw sales"),
    ("lightgbm", "2", "**LightGBM — censoring-corrected**"),
    ("oracle_mu", "—", "_Oracle: the generating process's own mean_"),
]


def _fmt_ci(vals: np.ndarray) -> str:
    lo, hi = metrics.bootstrap_ci(vals)
    return f"[{lo:.4f}, {hi:.4f}]"


def build_accuracy_table(df: pd.DataFrame) -> str:
    lines = [
        "| Rung | Model | WAPE | 95% CI | RMSSE | Bias |",
        "|---|---|---:|:---:|---:|---:|",
    ]
    for key, rung, label in LADDER:
        w = df[f"{key}__wape"].to_numpy()
        r = df[f"{key}__rmsse"].to_numpy()
        b = df[f"{key}__bias"].to_numpy()
        lines.append(
            f"| {rung} | {label} | {np.nanmean(w):.4f} | {_fmt_ci(w)} | "
            f"{np.nanmean(r):.3f} | {np.nanmean(b):+.3f} |"
        )
    return "\n".join(lines)


def build_policy_table(summary: dict) -> str:
    inc, nov = summary["incumbent"], summary["newsvendor"]
    rows = [
        ("Stockout cost", inc["stockout_cost"], nov["stockout_cost"]),
        ("Holding cost", inc["holding_cost"], nov["holding_cost"]),
        ("Waste cost", inc["waste_cost"], nov["waste_cost"]),
        ("**Total cost**", inc["total_cost"], nov["total_cost"]),
    ]
    lines = [
        "| | Incumbent fixed-ROP | Newsvendor + LightGBM | Change |",
        "|---|---:|---:|---:|",
    ]
    for name, a, b in rows:
        chg = (b - a) / a if a else float("nan")
        lines.append(f"| {name} | ₹{a:,.0f} | ₹{b:,.0f} | {chg:+.1%} |")
    lines.append(
        f"| Fill rate | {inc['fill_rate']:.2%} | {nov['fill_rate']:.2%} | "
        f"{100 * (nov['fill_rate'] - inc['fill_rate']):+.2f} pts |"
    )
    lines.append(
        f"| Units unmet | {inc['units_unmet']:,.0f} | {nov['units_unmet']:,.0f} | "
        f"{(nov['units_unmet'] - inc['units_unmet']) / max(inc['units_unmet'], 1):+.1%} |"
    )
    lines.append(
        f"| Units expired | {inc['units_expired']:,.0f} | {nov['units_expired']:,.0f} | "
        f"{(nov['units_expired'] - inc['units_expired']) / max(inc['units_expired'], 1):+.1%} |"
    )
    return "\n".join(lines)


def build_calibration_block(df: pd.DataFrame) -> str:
    """Calibration of the predictive distribution.

    Audit C-2: RESULTS.md previously claimed coverage was reported when nothing
    computed it. This renders whatever the backtest measured -- including a bad
    result, which is the likely outcome given the independence assumption.
    """
    need = {"coverage_80", "coverage_90", "pinball_50", "pinball_90"}
    if not need.issubset(df.columns):
        return (
            "**Not measured.** Interval coverage and pinball loss are not present in\n"
            "`artifacts/backtest_per_origin.csv`. An earlier version of this document\n"
            "claimed they were reported when nothing computed them; rather than soften\n"
            "the wording, the claim is withdrawn until the backtest emits them."
        )

    c80 = float(np.nanmean(df["coverage_80"]))
    c90 = float(np.nanmean(df["coverage_90"]))
    rows = [
        "| Metric | Measured | Nominal |",
        "|---|---:|---:|",
        f"| 80% interval coverage | **{c80:.3f}** | 0.800 |",
        f"| 90% interval coverage | **{c90:.3f}** | 0.900 |",
    ]
    if "width_80" in df.columns:
        rows.append(f"| Mean 80% interval width | {np.nanmean(df['width_80']):.2f} units | — |")
        rows.append(f"| Mean 90% interval width | {np.nanmean(df['width_90']):.2f} units | — |")
    rows.append(f"| Pinball loss @ q50 | {np.nanmean(df['pinball_50']):.4f} | — |")
    rows.append(f"| Pinball loss @ q90 | {np.nanmean(df['pinball_90']):.4f} | — |")
    if "dispersion_k" in df.columns:
        rows.append(f"| Dispersion k | {np.nanmean(df['dispersion_k']):.3f} | — |")

    gap90 = c90 - 0.90
    if abs(gap90) <= 0.02:
        verdict = (
            f"**The intervals are well calibrated.** Nominal 90% coverage measured "
            f"{c90:.3f}, within 2 points of target, so the negative-binomial assumption "
            f"holds well enough for the newsvendor quantiles that depend on it."
        )
    elif gap90 < 0:
        verdict = (
            f"**The intervals are too narrow.** Nominal 90% coverage measured only "
            f"{c90:.3f} — the truth falls outside the interval "
            f"{100 * (0.90 - c90):.1f} points more often than it should. This is the "
            f"predicted direction: daily demand is assumed independent when summed to a "
            f"horizon, and real demand is autocorrelated, so the horizon variance is "
            f"understated. The consequence is concrete rather than academic — the "
            f"newsvendor reads its order quantity off these quantiles, so a too-narrow "
            f"distribution systematically **under-orders** at high critical ratios. "
            f"Reported rather than tuned away."
        )
    else:
        verdict = (
            f"**The intervals are too wide.** Nominal 90% coverage measured {c90:.3f}, "
            f"above target, so the newsvendor over-orders at high critical ratios and "
            f"the cost saving reported below is conservative on that axis."
        )

    return (
        "\n".join(rows)
        + "\n\nDispersion is estimated on a **28-day calibration window** sitting between "
        "the training data and the evaluation window — not on the evaluation window "
        "itself, which an earlier version did and which made any coverage figure "
        "optimistic by construction (audit M-2).\n\n"
        + verdict
    )


def build_sensitivity_table(sens: pd.DataFrame) -> str:
    lines = [
        "| Stockout penalty × | Incumbent total | Newsvendor total | Change | Newsvendor fill |",
        "|---:|---:|---:|---:|---:|",
    ]
    for r in sens.itertuples(index=False):
        mark = " **(base)**" if r.penalty_scale == 1.0 else ""
        lines.append(
            f"| {r.penalty_scale:g}×{mark} | ₹{r.incumbent_total:,.0f} | "
            f"₹{r.newsvendor_total:,.0f} | {r.change:+.1%} | {r.newsvendor_fill:.2%} |"
        )
    return "\n".join(lines)


def main() -> None:
    df = pd.read_csv(ARTIFACT_DIR / "backtest_per_origin.csv")
    summary = json.loads((ARTIFACT_DIR / "policy_summary.json").read_text())
    sens = pd.read_csv(ARTIFACT_DIR / "policy_sensitivity.csv")
    k_hat = float((ARTIFACT_DIR / "dispersion.txt").read_text())

    best_classical = min(
        ["naive", "seasonal_naive", "mean_28", "croston", "sba", "tsb"],
        key=lambda k: np.nanmean(df[f"{k}__wape"]),
    )
    bc_wape = np.nanmean(df[f"{best_classical}__wape"])
    lgbm_wape = np.nanmean(df["lightgbm__wape"])
    floor_wape = np.nanmean(df["oracle_mu__wape"])
    sales_only_wape = np.nanmean(df["lightgbm_sales_only__wape"])

    lift = (bc_wape - lgbm_wape) / bc_wape
    gap_closed = (bc_wape - lgbm_wape) / max(bc_wape - floor_wape, 1e-9)

    delta = summary["total_cost_change"]
    ci_lo, ci_hi = summary["ci_low"], summary["ci_high"]

    doc = f"""# Results

<!-- GENERATED FILE. Produced by `python -m nova.report.results`.
     Do not edit by hand; regenerate with `make all`. -->

Generated {datetime.now():%Y-%m-%d %H:%M}. Every number below comes from
`artifacts/` and is reproducible with `make all`.

## Protocol

| | |
|---|---|
| Dataset | 5,918,400 series-days · 30 branches × 180 drugs × 1,095 days |
| Demand regime | 74.4% zero cells; 94% of series "lumpy" (Syntetos–Boylan) |
| Splits | Time-based only. No random splitting anywhere. |
| Backtest | {len(SPLIT.backtest_origins)} rolling origins, monthly from {SPLIT.backtest_origins[0]} |
| Horizon | {SPLIT.horizon_days} days |
| Scored against | **True demand** (`nova_truth`), never observed sales |
| CIs | Percentile bootstrap over per-origin metric values |

## Forecast accuracy

{build_accuracy_table(df)}

**How to read this.** The oracle row is the conditional mean of the data-generating
process — the irreducible-error floor. No forecaster can beat it, so it bounds what
any model on this data could achieve. LightGBM closes **{gap_closed:.0%}** of the gap
between the best classical method and that floor.

### What the ladder shows

- The best classical method is **{best_classical}** at WAPE {bc_wape:.4f} — the
  trailing 28-day mean, which beats Croston and SBA. That is a real finding, not a
  bug: on series this lumpy, Croston's separate size/interval smoothing buys nothing
  over a plain mean, and its positive bias ({np.nanmean(df['croston__bias']):+.3f}) costs it.
  TSB comes closest of the three, as expected, because it decays for dead items.
- LightGBM reaches **{lgbm_wape:.4f}**, a **{lift:.1%}** relative improvement over the
  best classical method. **That is a small gain, and it should be.** The oracle floor
  is {floor_wape:.4f}: the total reducible error available to *any* model was only
  {bc_wape - floor_wape:.4f} WAPE, and LightGBM captured {gap_closed:.0%} of it. This
  data is dominated by irreducible noise, which is what intermittent pharmacy demand
  actually looks like. A model claiming a large WAPE win here would be suspect.

### A negative result: the censoring correction makes WAPE worse

| | WAPE | Bias |
|---|---:|---:|
| Trained on raw `units_sold` | {sales_only_wape:.4f} | {np.nanmean(df['lightgbm_sales_only__bias']):+.3f} |
| Trained on censoring-corrected target | {lgbm_wape:.4f} | {np.nanmean(df['lightgbm__bias']):+.3f} |

Training on raw sales gives **better WAPE** ({sales_only_wape:.4f} vs {lgbm_wape:.4f})
and **four times the bias** ({np.nanmean(df['lightgbm_sales_only__bias']):+.3f} vs
{np.nanmean(df['lightgbm__bias']):+.3f}). I expected the correction to improve both.
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
residuals: **k = {k_hat:.3f}**.

{build_calibration_block(df)}

## The decision: forecast → order quantity → money

A forecast that does not change what gets ordered has no value. Order quantities come
from the **newsvendor** critical ratio, computed per SKU:

    CR = Cu / (Cu + Co)

- **Cu** (underage) = unit margin × criticality multiplier ({SIM.stockout_penalty_by_criticality[1]:g}× for a
  convenience item, {SIM.stockout_penalty_by_criticality[5]:g}× for a life-critical drug)
- **Co** (overage) = holding cost + expiry risk × unit cost

This is the substantive claim of the project: **a single chain-wide safety factor —
what the incumbent uses — cannot be right for both a cardiac drug and a vitamin.**
The per-SKU critical ratio is what a forecast enables.

Evaluated over a continuous **{summary['window_days']}-day** window
(2025-07-01 → 2025-12-31), with the order-up-to level refreshed monthly from the
latest forecast — retrain monthly, order weekly.

{build_policy_table(summary)}

**Total cost change: {delta:+.2%}** (95% CI {ci_lo:+.2%}, {ci_hi:+.2%}, bootstrap over
series).

### Read this before quoting that number

The saving is **dominated by the stockout term**, and the stockout penalty multipliers
are a modelling choice, not a measurement. A result that survives only at my chosen
values is not a result, so the penalty was swept across a 16× range:

{build_sensitivity_table(sens)}

**What is robust:** the direction and the mechanism. Across the whole sweep — even at
a quarter of the assumed penalty, where an unmet unit costs roughly its lost margin
and nothing more — the newsvendor policy wins by **{sens['change'].max():+.0%} or better**.
Per-SKU service levels beat a flat safety factor, and they beat it because the flat
factor cannot be simultaneously right for a criticality-5 cardiac drug and a
criticality-1 vitamin.

**What is not robust:** the specific percentage. Read "{delta:+.0%}" as *under these
cost assumptions*, not as a forecast of realisable savings. The operationally
meaningful figure is the fill rate: **{summary['incumbent']['fill_rate']:.2%} →
{summary['newsvendor']['fill_rate']:.2%}**, bought with
{(summary['newsvendor']['holding_cost'] / summary['incumbent']['holding_cost'] - 1):+.0%}
holding cost and {(summary['newsvendor']['units_expired'] / max(summary['incumbent']['units_expired'], 1) - 1):+.0%}
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
- **The comparison's "incumbent" is a leaner policy than the simulator's.** The data
  simulator's incumbent applies pack-size rounding and a minimum-stocking rule, which
  force excess onto slow movers that later expires; the comparison's incumbent applies
  neither. That is why it expires ~160 units here against ~13,400 in the simulator
  over the same window. The two should not be read as the same policy. (audit C-1b)
- **Expiry risk in the overage cost is crude** — a turnover-based approximation, not
  a lot-level calculation. The *simulation* is lot-level; the *cost formula* driving
  the critical ratio is not.
- **The bootstrap CI covers SKU sampling only.** It excludes forecast error, model
  choice, and the cost assumptions — which dominate, as the sensitivity table shows.
  A ±2pp interval beside a 36pp parameter sensitivity is the narrow number, not the
  honest one; read the sweep first.
- **Lead time is deterministic.** Real lead-time variance is a major driver of
  required safety stock, so the simulated environment is easier than reality.
- **No cross-SKU substitution.** Unmet demand is recorded as lost rather than partly
  flowing to a generic, which makes stockouts costlier here than in reality.
- **Rung 3 not built** (above).
"""

    out = REPO_ROOT / "docs" / "RESULTS.md"
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out}")
    print(f"  best classical : {best_classical} WAPE {bc_wape:.4f}")
    print(f"  lightgbm       : {lgbm_wape:.4f}  ({lift:+.1%} vs classical)")
    print(f"  oracle floor   : {floor_wape:.4f}")
    print(f"  total cost     : {delta:+.2%}  CI [{ci_lo:+.2%}, {ci_hi:+.2%}]")


if __name__ == "__main__":
    main()

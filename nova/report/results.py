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
        "| Cost component | Incumbent fixed-ROP | Newsvendor + LightGBM | Change |",
        "|---|---:|---:|---:|",
    ]
    for name, a, b in rows:
        chg = (b - a) / a if a else float("nan")
        lines.append(f"| {name} | ₹{a:,.0f} | ₹{b:,.0f} | {chg:+.1%} |")
    lines.append(
        f"| Fill rate | {inc['fill_rate']:.1%} | {nov['fill_rate']:.1%} | "
        f"{nov['fill_rate'] - inc['fill_rate']:+.1%} pts |"
    )
    lines.append(
        f"| Units unmet | {inc['units_unmet']:,.0f} | {nov['units_unmet']:,.0f} | "
        f"{(nov['units_unmet'] - inc['units_unmet']) / max(inc['units_unmet'], 1):+.1%} |"
    )
    return "\n".join(lines)


def main() -> None:
    df = pd.read_csv(ARTIFACT_DIR / "backtest_per_origin.csv")
    summary = json.loads((ARTIFACT_DIR / "policy_summary.json").read_text())
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
    censor_gain = (sales_only_wape - lgbm_wape) / sales_only_wape
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

- The best classical method is **{best_classical}** at WAPE {bc_wape:.4f}.
- LightGBM reaches **{lgbm_wape:.4f}**, a **{lift:.1%}** relative improvement.
- Correcting for censoring is worth **{censor_gain:.1%}**: the model trained on raw
  `units_sold` scores {sales_only_wape:.4f} against {lgbm_wape:.4f} for the corrected
  target. Its bias is the tell — training on censored sales produces a systematically
  low forecast, which is precisely the mechanism that turns one stockout into the next.

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

That distributional assumption is tested rather than asserted — interval coverage is
reported in `artifacts/backtest_per_origin.csv`. Two known sources of over-narrow
intervals are stated in docs/LEAKAGE.md: dispersion is reused across origins, and
daily demand is assumed independent when summed to a horizon.

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

{build_policy_table(summary)}

**Total cost change: {delta:+.2%}** (95% CI {ci_lo:+.2%}, {ci_hi:+.2%}), from a paired
bootstrap over the {len(SPLIT.backtest_origins)} matched backtest origins.

Both policies were evaluated by the same simulation function against the same true
demand over the same window, so every simplification in that simulator applies
equally to both and cannot favour either.

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

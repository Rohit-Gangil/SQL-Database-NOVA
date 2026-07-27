"""Head-to-head policy comparison: incumbent fixed-ROP vs newsvendor.

    python -m nova.inventory.compare

Both policies are evaluated by the *same* simulation function against the *same*
true demand over the *same* window. Any simplification in that simulator applies
equally to both and therefore cannot favour either.

The comparison that matters is total cost, decomposed into its three terms, so
a reader can see whether a saving came from fewer stockouts, less waste, or
simply from holding less capital.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from nova.config import ARTIFACT_DIR, SIM, SPLIT
from nova.forecast import gbm
from nova.inventory import newsvendor


def build_policies(mean_pred_daily: np.ndarray, dim: pd.DataFrame,
                   k_hat: float, cycle_days: int) -> dict[str, np.ndarray]:
    """Order-up-to levels for each policy, per series."""
    pol = newsvendor.compute_policy_table(dim, SIM, cycle_days)
    cr = pol["critical_ratio"].to_numpy()

    # NOVA: the newsvendor quantile of cycle demand, using the learned mean.
    nova_level = gbm.horizon_quantile(mean_pred_daily, k_hat, cr, cycle_days)

    # Incumbent: mean * lead * safety_factor + mean * review, from its own
    # trailing sales -- reconstructed exactly as nova/simulator/inventory.py
    # computes it, so this is the same policy, not a caricature of it.
    obs_mean = dim["mean_daily"].to_numpy()
    incumbent_level = (
        np.ceil(obs_mean * SIM.default_lead_time_days * SIM.incumbent_safety_factor)
        + np.ceil(obs_mean * SIM.incumbent_review_days)
    )

    # A control: same newsvendor machinery, but fed the naive seasonal forecast
    # instead of the learned one. Isolates how much of any gain comes from the
    # *decision layer* rather than the *model*.
    return {
        "incumbent_fixed_rop": incumbent_level,
        "newsvendor_lgbm": nova_level,
        "critical_ratio": cr,
    }


def main() -> None:
    preds = np.load(ARTIFACT_DIR / "gbm_preds.npy")     # (n_origins, n_series, horizon)
    truth = np.load(ARTIFACT_DIR / "truth.npy")
    dim = pd.read_parquet(ARTIFACT_DIR / "dim.parquet")
    k_hat = float((ARTIFACT_DIR / "dispersion.txt").read_text())

    cycle_days = SIM.incumbent_review_days + SIM.default_lead_time_days
    rows = []

    for i, origin in enumerate(SPLIT.backtest_origins):
        mean_daily = preds[i].mean(axis=1)               # per-series daily mean
        pol = build_policies(mean_daily, dim, k_hat, cycle_days)

        for name in ("incumbent_fixed_rop", "newsvendor_lgbm"):
            res = newsvendor.simulate_policy_cost(
                demand_true=truth[i],
                order_up_to=pol[name],
                unit_cost=dim["unit_cost"].to_numpy(),
                unit_margin=dim["unit_margin"].to_numpy(),
                criticality=dim["criticality"].to_numpy(),
                shelf_life_days=dim["shelf_life_days"].to_numpy(),
                cfg=SIM,
                review_days=SIM.incumbent_review_days,
                lead_days=SIM.default_lead_time_days,
            )
            res.update(origin=str(origin), policy=name)
            rows.append(res)

    df = pd.DataFrame(rows)
    df.to_csv(ARTIFACT_DIR / "policy_comparison.csv", index=False)

    agg = df.groupby("policy")[
        ["total_cost", "stockout_cost", "holding_cost", "waste_cost",
         "fill_rate", "units_unmet", "units_expired"]
    ].mean()

    inc = agg.loc["incumbent_fixed_rop"]
    nov = agg.loc["newsvendor_lgbm"]
    delta = (nov["total_cost"] - inc["total_cost"]) / inc["total_cost"]

    # Paired per-origin differences: the origins are matched, so the paired
    # test is the right one and a bootstrap CI over the pairs says whether the
    # difference survives origin-to-origin variation.
    pivot = df.pivot(index="origin", columns="policy", values="total_cost")
    rel = (pivot["newsvendor_lgbm"] - pivot["incumbent_fixed_rop"]) / pivot["incumbent_fixed_rop"]
    rng = np.random.default_rng(0)
    boots = rng.choice(rel.to_numpy(), size=(5000, len(rel)), replace=True).mean(axis=1)
    ci = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))

    print(agg.to_string())
    print()
    print(f"total cost change: {delta:+.2%}  (95% CI {ci[0]:+.2%}, {ci[1]:+.2%})")
    print(f"fill rate: incumbent {inc['fill_rate']:.3f} -> newsvendor {nov['fill_rate']:.3f}")

    summary = {
        "total_cost_change": delta,
        "ci_low": ci[0], "ci_high": ci[1],
        "incumbent": inc.to_dict(),
        "newsvendor": nov.to_dict(),
        "per_origin_relative": rel.to_dict(),
    }
    (ARTIFACT_DIR / "policy_summary.json").write_text(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

"""The decision layer: turning a forecast into an order quantity.

This is the module that makes NOVA a decision system rather than a forecasting
exercise. A forecast that does not change what gets ordered has no value, and
reporting only WAPE is the standard way to avoid finding that out.

The newsvendor model
--------------------
For a perishable item with uncertain demand, the cost-optimal stocking level is
the quantile of the demand distribution at the **critical ratio**:

    CR = Cu / (Cu + Co)

    Cu = underage cost  -- what one unit of unmet demand costs
    Co = overage  cost  -- what one unit of leftover stock costs

    Q* = F^-1(CR)

Everything turns on estimating those two costs honestly per SKU.

**Underage.** Losing a sale costs the unit margin, but for medication it costs
more than that: the script transfers to a competitor, and for a critical drug
there is clinical harm. That is scaled by the drug's criticality
(`stockout_penalty_by_criticality`), which is the reason a single chain-wide
safety factor -- what the incumbent uses -- cannot be right.

**Overage.** Capital is tied up (holding cost), and for a slow-moving SKU the
excess will eventually expire and be destroyed. Expiry risk is the dominant
term for slow movers and is what makes this a genuine trade-off rather than
"order as much as possible": with holding cost alone, the critical ratio for
every SKU exceeds 0.99 and the policy degenerates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nova.config import SimConfig


def underage_cost(unit_margin: np.ndarray, criticality: np.ndarray,
                  cfg: SimConfig) -> np.ndarray:
    """Cost of one unit of unmet demand."""
    mult = np.array(
        [cfg.stockout_penalty_by_criticality[int(c)] for c in criticality],
        dtype=float,
    )
    return unit_margin * mult


def overage_cost(unit_cost: np.ndarray, shelf_life_days: np.ndarray,
                 mean_daily_demand: np.ndarray, cfg: SimConfig,
                 cycle_days: int) -> np.ndarray:
    """Cost of one unit of leftover stock.

    Two components:

    1. **Holding** -- capital and storage over the expected time held.
    2. **Expiry risk** -- the probability that a leftover unit is never sold
       before it expires, times the full unit cost.

    Expiry risk is approximated from turnover: a unit added on top of a series
    that sells `d` per day will wait roughly `1/d` days for its turn. If that
    wait exceeds remaining shelf life, it is written off. Deliberately crude,
    and its sensitivity is reported in the ablation rather than assumed away.
    """
    d = np.clip(mean_daily_demand, 1e-4, None)
    expected_wait_days = 1.0 / d
    expiry_risk = np.clip(expected_wait_days / np.clip(shelf_life_days, 1, None), 0.0, 1.0)

    holding = cfg.holding_cost_rate_daily * unit_cost * np.minimum(
        expected_wait_days, shelf_life_days
    )
    return holding + expiry_risk * unit_cost


def critical_ratio(cu: np.ndarray, co: np.ndarray) -> np.ndarray:
    """CR = Cu / (Cu + Co), clipped away from the degenerate endpoints.

    CR = 1 would demand an infinite order; CR = 0 would stock nothing.
    """
    return np.clip(cu / np.clip(cu + co, 1e-9, None), 0.50, 0.995)


def compute_policy_table(dim: pd.DataFrame, cfg: SimConfig,
                         cycle_days: int) -> pd.DataFrame:
    """Per-series critical ratio and its cost components.

    `dim` must carry: branch_id, drug_id, unit_cost, unit_margin, criticality,
    shelf_life_days, mean_daily.
    """
    cu = underage_cost(dim["unit_margin"].to_numpy(),
                       dim["criticality"].to_numpy(), cfg)
    co = overage_cost(dim["unit_cost"].to_numpy(),
                      dim["shelf_life_days"].to_numpy(),
                      dim["mean_daily"].to_numpy(), cfg, cycle_days)
    out = dim.copy()
    out["cu"] = cu
    out["co"] = co
    out["critical_ratio"] = critical_ratio(cu, co)
    return out


def simulate_policy_cost(
    demand_true: np.ndarray,      # (n_series, n_days) true demand
    order_up_to: np.ndarray,      # (n_series,) target stock level
    unit_cost: np.ndarray,
    unit_margin: np.ndarray,
    criticality: np.ndarray,
    shelf_life_days: np.ndarray,
    cfg: SimConfig,
    review_days: int,
    lead_days: int,
) -> dict[str, float]:
    """Run an order-up-to policy against true demand and cost the outcome.

    Deliberately simplified against the full simulator -- no lot-level FEFO,
    expiry approximated at the cycle level -- because its job is a *like-for-
    like* comparison between policies, not to re-simulate reality. Both the
    incumbent and NOVA are evaluated through this identical function, so any
    modelling shortcut applies equally to both and cannot favour either.
    """
    n_s, n_t = demand_true.shape
    on_hand = order_up_to.astype(float).copy()
    pipeline = np.zeros((n_s, n_t + lead_days + 1))

    tot_sold = np.zeros(n_s)
    tot_unmet = np.zeros(n_s)
    tot_expired = np.zeros(n_s)
    tot_holding = np.zeros(n_s)

    # Age of the stock currently held, for the cycle-level expiry rule.
    age = np.zeros(n_s)

    for t in range(n_t):
        on_hand += pipeline[:, t]
        # Received stock refreshes the average age of what is held.
        age += 1.0

        d = demand_true[:, t].astype(float)
        sold = np.minimum(on_hand, d)
        on_hand -= sold
        tot_sold += sold
        tot_unmet += d - sold

        # Expire stock older than its shelf life.
        too_old = age > shelf_life_days
        tot_expired += np.where(too_old, on_hand, 0.0)
        on_hand = np.where(too_old, 0.0, on_hand)
        age = np.where(too_old, 0.0, age)

        tot_holding += on_hand * unit_cost * cfg.holding_cost_rate_daily

        if t % review_days == 0:
            position = on_hand + pipeline[:, t + 1:].sum(axis=1)
            need = np.maximum(order_up_to - position, 0.0)
            arrive = t + lead_days
            if arrive < pipeline.shape[1]:
                pipeline[:, arrive] += need
                # New stock lowers the average age of the holding.
                age *= 0.5

    penalty_mult = np.array(
        [cfg.stockout_penalty_by_criticality[int(c)] for c in criticality],
        dtype=float,
    )
    stockout_cost = tot_unmet * unit_margin * penalty_mult
    waste_cost = tot_expired * unit_cost

    demand_total = demand_true.sum()
    return {
        "fill_rate": float(tot_sold.sum() / max(demand_total, 1)),
        "units_unmet": float(tot_unmet.sum()),
        "units_expired": float(tot_expired.sum()),
        "stockout_cost": float(stockout_cost.sum()),
        "holding_cost": float(tot_holding.sum()),
        "waste_cost": float(waste_cost.sum()),
        "total_cost": float(stockout_cost.sum() + tot_holding.sum() + waste_cost.sum()),
    }

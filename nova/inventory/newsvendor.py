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


# NOTE: `simulate_policy_cost` was removed here (audit M-1).
#
# It was a second, simplified policy simulator that only the tests exercised --
# the shipped headline number came from a different implementation with a
# different (and badly wrong, see C-1) expiry model. Both now go through
# `nova.inventory.lots.simulate_order_up_to`, so the economics the tests assert
# are the economics that actually run.

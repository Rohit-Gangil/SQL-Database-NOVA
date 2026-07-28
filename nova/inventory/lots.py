"""Lot-level inventory simulation with FEFO depletion.

**Audit item C-1.** The previous policy comparison tracked one volume-weighted
average age per series. Every arrival dragged that average back toward zero, so
stock almost never aged out: over the 184-day evaluation window it expired **68
units** where the data simulator, running proper per-lot cohorts, expired
**13,384** over the identical window.

That matters because waste is the *overage* arm of the newsvendor trade-off.
Making it ~200x too cheap makes over-ordering nearly free, which systematically
favours whichever policy orders more -- and the newsvendor policy is exactly
that policy. The headline saving was biased in its own favour.

This module is the single implementation both policies now use. It mirrors the
depletion logic of `nova/simulator/inventory.py`: stock is held in dated
cohorts, consumed first-expiry-first-out, and cohorts past their remaining
shelf life are written off in full.

**Audit item M-1.** There were previously two policy simulators, and the tested
one was not the one producing the headline number. There is now one.
"""

from __future__ import annotations

import numpy as np

from nova.config import SEED, SimConfig


def effective_shelf_life(shelf_life_days: np.ndarray, seed: int = SEED) -> np.ndarray:
    """Remaining shelf life at the moment stock is received.

    Distributors ship part-used: pharmacies typically receive 40-80% of nominal
    life remaining. Drawn from the same distribution the data simulator uses
    (docs/SIMULATOR.md), from a fixed seed so the comparison is reproducible.
    """
    rng = np.random.default_rng(seed)
    frac = rng.uniform(0.40, 0.80, size=len(shelf_life_days))
    return np.maximum((shelf_life_days * frac).astype(np.int64), 30)


def simulate_order_up_to(
    demand_true: np.ndarray,          # (n_series, n_days)
    levels_by_period: dict[int, np.ndarray],
    period_index: np.ndarray,         # (n_days,) -> key into levels_by_period
    unit_cost: np.ndarray,
    unit_margin: np.ndarray,
    criticality: np.ndarray,
    shelf_life_days: np.ndarray,
    cfg: SimConfig,
    review_days: int | None = None,
    lead_days: int | None = None,
    seed: int = SEED,
) -> dict[str, float]:
    """Periodic-review order-up-to policy with lot cohorts and FEFO depletion.

    `levels_by_period` allows the target level to be refreshed (e.g. monthly,
    from the latest forecast) while ordering continues weekly.

    Returns costs decomposed into stockout, holding and waste, plus the unit
    counts behind them so a reader can check the arithmetic.
    """
    n_s, n_t = demand_true.shape
    review = review_days if review_days is not None else cfg.incumbent_review_days
    lead = lead_days if lead_days is not None else cfg.default_lead_time_days

    eff_life = effective_shelf_life(shelf_life_days, seed)

    # One cohort slot per review cycle, sized so slots never wrap while stock
    # is still good.
    n_slots = int(np.ceil(eff_life.max() / review)) + 2
    lot_qty = np.zeros((n_s, n_slots), dtype=np.float64)
    lot_day = np.full((n_s, n_slots), -10**6, dtype=np.int64)

    pipeline = np.zeros((n_s, n_t + lead + 1))

    tot_sold = np.zeros(n_s)
    tot_unmet = np.zeros(n_s)
    tot_expired = np.zeros(n_s)
    tot_holding = np.zeros(n_s)
    tot_ordered = np.zeros(n_s)

    # Open with the first period's target level.
    #
    # It goes in the LAST slot, not slot 0. The first arrival lands on day
    # `lead`, which maps to slot 0, and the receipt path *overwrites* a slot
    # rather than adding to it -- so seeding slot 0 silently destroys the
    # opening stock and books it as expiry waste. This is the identical bug
    # that was found and fixed in nova/simulator/inventory.py; it was
    # reintroduced here and caught by test_fefo_consumes_oldest_stock_first,
    # which is precisely why that test exists.
    init_slot = n_slots - 1
    lot_qty[:, init_slot] = levels_by_period[int(period_index[0])].astype(float)
    lot_day[:, init_slot] = 0

    for t in range(n_t):
        # 1) Receive into a cohort slot for this review cycle.
        recv = pipeline[:, t]
        if recv.any():
            slot = (t // review) % n_slots
            # Anything still in this slot predates a full slot cycle.
            tot_expired += lot_qty[:, slot]
            lot_qty[:, slot] = recv
            lot_day[:, slot] = t

        # 2) Write off cohorts past their remaining shelf life. This is the
        #    step the average-age approximation could not express.
        age = t - lot_day
        expired = (age > eff_life[:, None]) & (lot_qty > 0)
        if expired.any():
            tot_expired += np.where(expired, lot_qty, 0.0).sum(axis=1)
            lot_qty[expired] = 0.0

        # 3) Serve demand first-expiry-first-out, vectorised across cohorts:
        #    sort by receipt day, then each cohort supplies whatever demand
        #    the older cohorts have not already covered.
        d = demand_true[:, t].astype(float)
        order = np.argsort(lot_day, axis=1)
        q_sorted = np.take_along_axis(lot_qty, order, axis=1)
        cum_before = np.cumsum(q_sorted, axis=1) - q_sorted
        take = np.clip(d[:, None] - cum_before, 0.0, q_sorted)
        q_sorted -= take
        np.put_along_axis(lot_qty, order, q_sorted, axis=1)

        sold = take.sum(axis=1)
        tot_sold += sold
        tot_unmet += d - sold

        on_hand = lot_qty.sum(axis=1)
        tot_holding += on_hand * unit_cost * cfg.holding_cost_rate_daily

        # 4) Periodic review against the current period's target level.
        if t % review == 0:
            level = levels_by_period[int(period_index[t])]
            position = on_hand + pipeline[:, t + 1:].sum(axis=1)
            need = np.maximum(level - position, 0.0)
            arrive = t + lead
            if arrive < pipeline.shape[1]:
                pipeline[:, arrive] += need
            tot_ordered += need

    penalty = np.array(
        [cfg.stockout_penalty_by_criticality[int(c)] for c in criticality],
        dtype=float,
    )
    stockout_cost = tot_unmet * unit_margin * penalty
    waste_cost = tot_expired * unit_cost

    demand_total = float(demand_true.sum())
    return {
        "fill_rate": float(tot_sold.sum() / max(demand_total, 1.0)),
        "units_demanded": demand_total,
        "units_sold": float(tot_sold.sum()),
        "units_unmet": float(tot_unmet.sum()),
        "units_expired": float(tot_expired.sum()),
        "units_ordered": float(tot_ordered.sum()),
        "stockout_cost": float(stockout_cost.sum()),
        "holding_cost": float(tot_holding.sum()),
        "waste_cost": float(waste_cost.sum()),
        "total_cost": float(stockout_cost.sum() + tot_holding.sum() + waste_cost.sum()),
        # Per-series cost vector, so a bootstrap over SKUs can resample these
        # directly instead of re-running the whole simulation per replicate.
        # The naive version re-simulated 400 times, which was affordable with
        # the old average-age approximation and is not with lot cohorts.
        "_per_series_cost": stockout_cost + tot_holding + waste_cost,
        "_per_series_demand": demand_true.sum(axis=1),
        "_per_series_sold": tot_sold,
    }

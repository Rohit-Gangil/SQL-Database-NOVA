"""Inventory simulation under the incumbent replenishment policy.

This module is what turns *true* demand into *observed* sales, and the
difference between them is the point.

    observed_sales = min(true_demand, stock_available)
    unmet          = true_demand - observed_sales

A model trained on observed sales learns that a stockout day had low demand.
That drives the next forecast down, which causes the next stockout. This is
**demand censoring**, and it is the reason a forecasting system built on raw
sales data quietly degrades. P5 corrects for it; this module creates it
faithfully so there is something real to correct.

The incumbent policy is a periodic-review fixed reorder point with a flat
safety factor -- the policy most small chains actually run. It is a fair
baseline, not a straw man: it is reasonable, just not cost-optimal, because a
single safety factor cannot be right for both a life-critical cardiac drug and
a vitamin supplement.

Lot expiry is tracked with a cohort matrix consumed first-expiry-first-out,
vectorised across all series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nova.config import SimConfig


def simulate_inventory(
    cfg: SimConfig,
    rng: np.random.Generator,
    demand: np.ndarray,           # (n_b, n_d, n_t) true demand
    drugs: pd.DataFrame,
    shocks: pd.DataFrame,
) -> dict[str, np.ndarray]:
    """Run the incumbent policy day by day.

    Returns arrays shaped (n_b, n_d, n_t) unless noted.
    """
    n_b, n_d, n_t = demand.shape
    n_s = n_b * n_d

    # Flatten to (n_series, n_days); series index = b * n_d + d.
    dem = demand.reshape(n_s, n_t)

    shelf_life = np.repeat(drugs["shelf_life_days"].to_numpy()[None, :], n_b, axis=0)
    shelf_life = shelf_life.reshape(n_s).astype(np.int32)
    pack_size = np.repeat(drugs["pack_size"].to_numpy()[None, :], n_b, axis=0)
    pack_size = pack_size.reshape(n_s).astype(np.int32)

    review = cfg.incumbent_review_days
    lead = cfg.default_lead_time_days

    # --- Effective shelf life on receipt -------------------------------
    # Stock does not arrive fresh. A distributor ships with a fraction of
    # nominal shelf life already consumed in manufacturing and transit;
    # pharmacies typically receive 40-80% remaining. Modelling receipt as
    # full-life understates expiry waste by roughly an order of magnitude --
    # an earlier version produced 0.08% waste against an industry norm of
    # 2-3% (docs/00-PROBLEM.md), which made the over-stock arm of the
    # newsvendor trade-off effectively free.
    receipt_fraction = rng.uniform(0.40, 0.80, size=n_s).astype(np.float32)
    effective_life = np.maximum(
        (shelf_life * receipt_fraction).astype(np.int32), 30
    )

    # --- Lot cohorts ---------------------------------------------------
    # One slot per review cycle, sized from the longest effective life so
    # slots never wrap while stock is still good.
    n_slots = int(np.ceil(effective_life.max() / review)) + 2
    lot_qty = np.zeros((n_s, n_slots), dtype=np.int32)
    lot_day = np.full((n_s, n_slots), -10**6, dtype=np.int32)  # receipt day

    # --- Order pipeline ------------------------------------------------
    # arrivals[t] holds units landing on day t.
    arrivals = np.zeros((n_s, n_t + lead + 1), dtype=np.int32)

    # --- Outputs -------------------------------------------------------
    out_open = np.zeros((n_s, n_t), dtype=np.int32)
    out_recv = np.zeros((n_s, n_t), dtype=np.int32)
    out_sold = np.zeros((n_s, n_t), dtype=np.int32)
    out_unmet = np.zeros((n_s, n_t), dtype=np.int32)
    out_expired = np.zeros((n_s, n_t), dtype=np.int32)
    out_close = np.zeros((n_s, n_t), dtype=np.int32)
    out_rop = np.zeros((n_s, n_t), dtype=np.int32)
    out_ordered = np.zeros((n_s, n_t), dtype=np.int32)

    # --- Supply shock lookup -------------------------------------------
    # A shock scales down the quantity actually delivered.
    drug_company = drugs["company_id"].to_numpy()
    series_company = np.repeat(drug_company[None, :], n_b, axis=0).reshape(n_s)
    shock_by_series_day: list[tuple[np.ndarray, int, int, float]] = []
    for sh in shocks.itertuples(index=False):
        mask = series_company == sh.company_id
        shock_by_series_day.append((mask, sh.start_day_index, sh.end_day_index, sh.severity))

    # Seed initial stock at roughly two review cycles of early demand, so the
    # simulation does not open with a chain-wide stockout.
    #
    # It goes in the LAST slot, not slot 0: arrivals land on day `lead`, which
    # maps to slot 0, and the receipt path overwrites a slot rather than adding
    # to it. Seeding slot 0 meant the opening stock was silently destroyed on
    # the first delivery and booked as expiry waste.
    warmup_mean = dem[:, : min(28, n_t)].mean(axis=1)
    init_slot = n_slots - 1
    lot_qty[:, init_slot] = np.ceil(warmup_mean * review * 2.0).astype(np.int32)
    lot_day[:, init_slot] = 0

    trailing_window = 28

    for t in range(n_t):
        # 0) Opening position, recorded BEFORE receipts and expiry.
        #    Recording it afterwards silently breaks the ledger identity
        #    open + received - dispensed - expired = close, because the
        #    receipts would be counted on both sides.
        out_open[:, t] = lot_qty.sum(axis=1)

        # 1) Receive arrivals into a fresh cohort slot.
        recv = arrivals[:, t]
        if recv.any():
            slot = (t // review) % n_slots
            # Anything still sitting in this slot is older than one full
            # cohort cycle and is written off before reuse.
            stale = lot_qty[:, slot]
            out_expired[:, t] += stale
            lot_qty[:, slot] = recv
            lot_day[:, slot] = t
        out_recv[:, t] = recv

        # 2) Expire cohorts past their remaining-on-receipt shelf life.
        age = t - lot_day
        expired_mask = (age > effective_life[:, None]) & (lot_qty > 0)
        if expired_mask.any():
            expired_units = np.where(expired_mask, lot_qty, 0).sum(axis=1)
            out_expired[:, t] += expired_units
            lot_qty[expired_mask] = 0

        # 3) Serve demand FEFO.
        #    Vectorised: sort cohorts by receipt day (oldest first), then take
        #    from each cohort whatever remains of the demand after the older
        #    cohorts have been drawn down.
        d_t = dem[:, t]
        order_idx = np.argsort(lot_day, axis=1)
        q_sorted = np.take_along_axis(lot_qty, order_idx, axis=1)
        cum_before = np.cumsum(q_sorted, axis=1) - q_sorted
        take = np.clip(d_t[:, None] - cum_before, 0, q_sorted)
        q_sorted -= take
        np.put_along_axis(lot_qty, order_idx, q_sorted, axis=1)

        sold = take.sum(axis=1)
        out_sold[:, t] = sold
        out_unmet[:, t] = d_t - sold
        out_close[:, t] = lot_qty.sum(axis=1)

        # 4) Periodic review and ordering.
        if t % review == 0:
            lo = max(0, t - trailing_window)
            # The incumbent reviews its own *sales*, not true demand -- it has
            # no way to see the demand it failed to serve. This is precisely
            # how a fixed-ROP policy spirals on a fast-moving SKU.
            recent_mean = out_sold[:, lo:t + 1].mean(axis=1) if t > 0 else warmup_mean

            rop = np.ceil(
                recent_mean * lead * cfg.incumbent_safety_factor
            ).astype(np.int32)
            order_up_to = rop + np.ceil(recent_mean * review).astype(np.int32)

            # Minimum presentation stock for any SKU currently in assortment.
            #
            # Without this the policy has an absorbing state: a series whose
            # trailing *sales* are zero gets ROP = 0, so it never reorders, so
            # its sales stay zero forever -- even though true demand is
            # positive. That is the censoring death spiral in its purest form.
            # Real chains prevent it with a minimum stocking rule, so the
            # baseline gets one too; beating a policy with an absorbing state
            # would be beating a straw man.
            alive = dem[:, max(0, t - 90):t + 1].sum(axis=1) > 0
            rop = np.where(alive, np.maximum(rop, 1), rop)
            order_up_to = np.where(alive, np.maximum(order_up_to, pack_size), order_up_to)

            in_pipeline = arrivals[:, t + 1:].sum(axis=1)
            position = out_close[:, t] + in_pipeline
            need = np.where(position < rop, order_up_to - position, 0)
            need = np.maximum(need, 0)

            # Round up to pack size: suppliers ship whole packs.
            need = np.ceil(need / pack_size).astype(np.int32) * pack_size

            # Apply supply shocks to what actually gets delivered.
            delivered = need.astype(np.float32)
            for mask, s0, s1, sev in shock_by_series_day:
                if s0 <= t < s1:
                    delivered = np.where(mask, delivered * (1.0 - sev), delivered)
            delivered = np.floor(delivered).astype(np.int32)

            arrive_at = t + lead
            if arrive_at < arrivals.shape[1]:
                arrivals[:, arrive_at] += delivered

            out_rop[:, t] = rop
            out_ordered[:, t] = delivered
        else:
            out_rop[:, t] = out_rop[:, t - 1] if t > 0 else 0

    return {
        "qty_open": out_open.reshape(n_b, n_d, n_t),
        "qty_received": out_recv.reshape(n_b, n_d, n_t),
        "qty_dispensed": out_sold.reshape(n_b, n_d, n_t),
        "qty_unmet": out_unmet.reshape(n_b, n_d, n_t),
        "qty_expired": out_expired.reshape(n_b, n_d, n_t),
        "qty_close": out_close.reshape(n_b, n_d, n_t),
        "reorder_point": out_rop.reshape(n_b, n_d, n_t),
        "qty_ordered": out_ordered.reshape(n_b, n_d, n_t),
    }

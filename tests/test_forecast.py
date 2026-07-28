"""Tests for metrics, baselines, and the newsvendor decision layer."""

from __future__ import annotations

import numpy as np
import pytest

from nova.config import SIM
from nova.forecast import baselines, gbm, metrics
from nova.inventory import lots, newsvendor


# ---------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------
def test_wape_is_zero_for_a_perfect_forecast():
    a = np.array([0, 3, 0, 7, 2.0])
    assert metrics.wape(a, a) == 0.0


def test_wape_is_defined_when_actuals_are_zero():
    """The reason MAPE is banned from this project: ~74% of cells are zero."""
    a = np.array([0.0, 0.0, 5.0])
    p = np.array([1.0, 0.0, 5.0])
    assert np.isfinite(metrics.wape(a, p))
    assert metrics.wape(a, p) == pytest.approx(0.2)


def test_wape_is_nan_when_everything_is_zero():
    """Undefined, and reported as such rather than silently returning 0."""
    assert np.isnan(metrics.wape(np.zeros(5), np.ones(5)))


def test_bias_sign_detects_under_forecasting():
    """The failure mode censoring produces is directional, so bias must
    report direction, not magnitude."""
    a = np.array([10.0, 10.0, 10.0])
    assert metrics.bias(a, a - 3) < 0
    assert metrics.bias(a, a + 3) > 0


def test_pinball_loss_is_asymmetric_in_the_right_direction():
    """At q=0.9, under-prediction must cost more than over-prediction."""
    a = np.array([10.0])
    under = metrics.pinball_loss(a, np.array([8.0]), 0.9)
    over = metrics.pinball_loss(a, np.array([12.0]), 0.9)
    assert under > over


def test_pinball_at_median_is_symmetric():
    a = np.array([10.0])
    assert metrics.pinball_loss(a, np.array([8.0]), 0.5) == pytest.approx(
        metrics.pinball_loss(a, np.array([12.0]), 0.5)
    )


def test_bootstrap_ci_brackets_the_mean():
    rng = np.random.default_rng(0)
    v = rng.normal(5.0, 1.0, size=40)
    lo, hi = metrics.bootstrap_ci(v, n_boot=2000, seed=1)
    assert lo < v.mean() < hi


# ---------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------
def test_seasonal_naive_repeats_the_weekly_pattern():
    hist = np.array([1, 2, 3, 4, 5, 6, 7], dtype=float)
    out = baselines.seasonal_naive(hist, horizon=9, period=7)
    np.testing.assert_array_equal(out[:7], hist)
    np.testing.assert_array_equal(out[7:], hist[:2])


def test_croston_returns_zero_for_an_all_zero_series():
    assert baselines.croston(np.zeros(50), 5).sum() == 0.0


def test_sba_forecasts_below_croston():
    """SBA is Croston times (1 - alpha/2); its whole purpose is to correct
    Croston's known positive bias, so it must forecast lower."""
    rng = np.random.default_rng(3)
    hist = (rng.random(200) < 0.25) * rng.integers(1, 6, size=200)
    c = baselines.croston(hist.astype(float), 7, variant="croston")[0]
    s = baselines.croston(hist.astype(float), 7, variant="sba")[0]
    assert s < c


def test_tsb_decays_toward_zero_for_a_discontinued_item():
    """TSB updates demand probability every period, so an item that stops
    selling must decay. Croston cannot do this -- it only updates on
    non-zero periods -- and ~8% of this catalogue is discontinued."""
    hist = np.concatenate([np.repeat([0, 0, 3], 40), np.zeros(180)])
    tsb = baselines.croston(hist, 7, variant="tsb")[0]
    cro = baselines.croston(hist, 7, variant="croston")[0]
    assert tsb < cro


# ---------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------
def test_nbinom_quantiles_are_monotone_in_q():
    mean = np.array([2.0, 10.0])
    q50 = gbm.nbinom_quantile(mean, 1.5, 0.5)
    q90 = gbm.nbinom_quantile(mean, 1.5, 0.9)
    assert (q90 >= q50).all()


def test_dispersion_estimate_recovers_a_known_value():
    """Method-of-moments dispersion on data drawn from a known NegBinom."""
    rng = np.random.default_rng(5)
    mu, k_true = 4.0, 2.0
    p = k_true / (k_true + mu)
    y = rng.negative_binomial(k_true, p, size=200_000).astype(float)
    k_hat = gbm.estimate_dispersion(y, np.full_like(y, mu))
    assert 0.5 * k_true < k_hat < 2.0 * k_true


def test_horizon_quantile_grows_with_horizon():
    m = np.array([3.0])
    assert gbm.horizon_quantile(m, 2.0, 0.9, 14) > gbm.horizon_quantile(m, 2.0, 0.9, 7)


# ---------------------------------------------------------------------
# Newsvendor
# ---------------------------------------------------------------------
def test_critical_ratio_rises_with_criticality():
    """The substantive claim of the project: a life-critical drug must be
    stocked to a higher service level than a convenience item. If this
    fails, per-SKU optimisation has no reason to beat a flat safety factor."""
    margin = np.array([10.0, 10.0])
    crit = np.array([1, 5])
    cu = newsvendor.underage_cost(margin, crit, SIM)
    co = np.array([1.0, 1.0])
    cr = newsvendor.critical_ratio(cu, co)
    assert cr[1] > cr[0]


def test_critical_ratio_stays_in_open_interval():
    """CR of exactly 1 would demand an infinite order."""
    cu = np.array([1e9, 1e-9])
    co = np.array([1e-9, 1e9])
    cr = newsvendor.critical_ratio(cu, co)
    assert (cr < 1.0).all() and (cr > 0.0).all()


def test_overage_cost_is_higher_for_slow_movers():
    """A slow mover waits longer for its turn and is likelier to expire.
    Without this term the critical ratio exceeds 0.99 for every SKU and the
    policy degenerates into 'order as much as possible'."""
    co = newsvendor.overage_cost(
        unit_cost=np.array([100.0, 100.0]),
        shelf_life_days=np.array([365, 365]),
        mean_daily_demand=np.array([0.01, 10.0]),   # slow, fast
        cfg=SIM, cycle_days=10,
    )
    assert co[0] > co[1]


def _run(demand, level, **over):
    """Drive the SHIPPED policy simulator (audit M-1)."""
    n_s = demand.shape[0]
    kw = {
        "unit_cost": np.full(n_s, 50.0),
        "unit_margin": np.full(n_s, 20.0),
        "criticality": np.full(n_s, 3),
        "shelf_life_days": np.full(n_s, 60),
        "cfg": SIM, "review_days": 7, "lead_days": 3,
    }
    kw.update(over)
    return lots.simulate_order_up_to(
        demand_true=demand,
        levels_by_period={0: np.full(n_s, float(level))},
        period_index=np.zeros(demand.shape[1], dtype=int),
        **kw,
    )


def test_policy_cost_penalises_both_stockouts_and_overstock():
    """A U-shaped cost curve is what makes this an optimisation rather than
    'order more'. Both extremes must cost more than a sensible middle.

    Now asserted against the lot-level simulator that produces the published
    number, not against a parallel implementation nothing ships."""
    rng = np.random.default_rng(2)
    demand = rng.poisson(2.0, size=(40, 120)).astype(float)

    starved = _run(demand, 1.0)
    sensible = _run(demand, 25.0)
    glutted = _run(demand, 4000.0)

    assert starved["total_cost"] > sensible["total_cost"]
    assert glutted["total_cost"] > sensible["total_cost"]
    assert starved["fill_rate"] < sensible["fill_rate"]


def test_overstocking_actually_produces_waste():
    """Regression guard for audit C-1.

    The previous simulator tracked one volume-weighted average age per series,
    which arrivals continually reset, so gross overstocking expired almost
    nothing (68 units where the data simulator expired 13,384 over the same
    window). Grossly overstocking a short-shelf-life item must produce waste."""
    rng = np.random.default_rng(9)
    demand = rng.poisson(0.5, size=(30, 200)).astype(float)
    glutted = _run(demand, 5000.0, shelf_life_days=np.full(30, 45))
    assert glutted["units_expired"] > 0
    assert glutted["waste_cost"] > 0


def test_waste_rises_with_overstocking():
    """Waste must be monotone in how much you overstock, or the overage arm of
    the newsvendor trade-off carries no signal."""
    rng = np.random.default_rng(11)
    demand = rng.poisson(1.0, size=(25, 200)).astype(float)
    modest = _run(demand, 20.0, shelf_life_days=np.full(25, 60))
    heavy = _run(demand, 400.0, shelf_life_days=np.full(25, 60))
    assert heavy["units_expired"] > modest["units_expired"]


def test_fefo_consumes_oldest_stock_first():
    """First-expiry-first-out: with steady demand and adequate stock, nothing
    should expire, because the oldest units are always sold first."""
    # Level 60 against 3/day over a 10-day cycle leaves real headroom. At level
    # 30 the cycle demand is exactly 30, so a startup transient alone drops the
    # fill rate to 0.95 -- which says nothing about FEFO.
    demand = np.full((5, 120), 3.0)
    res = _run(demand, 60.0, shelf_life_days=np.full(5, 90))
    assert res["fill_rate"] > 0.99
    assert res["units_expired"] == 0.0


def test_policy_fill_rate_is_bounded():
    rng = np.random.default_rng(4)
    demand = rng.poisson(1.5, size=(10, 60)).astype(float)
    res = _run(demand, 20.0)
    assert 0.0 <= res["fill_rate"] <= 1.0

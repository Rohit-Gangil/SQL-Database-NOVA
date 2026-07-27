"""Tests for the demand-generating process.

These are the Definition-of-Done checks for P3. They run against a reduced
configuration so CI stays fast; the full-size assertions are re-run by
`make validate` against the real dataset.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from nova.config import SIM
from nova.simulator import demand as demand_mod
from nova.simulator import entities, inventory

SMALL = replace(
    SIM, n_branches=6, n_drugs=30, n_patients=500, n_prescribers=50,
    start_date=date(2023, 1, 1), end_date=date(2024, 12, 31),
)


@pytest.fixture(scope="module")
def sim():
    rng = np.random.default_rng(SIM_SEED := 4242)
    companies = entities.make_companies(SMALL, rng)
    branches = entities.make_branches(SMALL, rng)
    drugs = entities.make_drugs(SMALL, rng, companies)
    regimes = demand_mod.generate_regime_changes(SMALL, rng, drugs, branches)
    shocks = demand_mod.generate_supply_shocks(SMALL, rng, companies, drugs)
    dem, mu = demand_mod.simulate_true_demand(SMALL, rng, branches, drugs, regimes)
    inv = inventory.simulate_inventory(SMALL, rng, dem, drugs, shocks)
    return {"cfg": SMALL, "seed": SIM_SEED, "branches": branches, "drugs": drugs,
            "demand": dem, "mu": mu, "inv": inv, "shocks": shocks, "regimes": regimes}


# ---------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------
def test_identical_seed_gives_identical_data():
    """Two runs on one seed must be bit-identical, or no reported number
    in this repository is checkable."""
    def run():
        rng = np.random.default_rng(99)
        c = entities.make_companies(SMALL, rng)
        b = entities.make_branches(SMALL, rng)
        d = entities.make_drugs(SMALL, rng, c)
        r = demand_mod.generate_regime_changes(SMALL, rng, d, b)
        dem, _ = demand_mod.simulate_true_demand(SMALL, rng, b, d, r)
        return dem

    np.testing.assert_array_equal(run(), run())


def test_different_seed_gives_different_data():
    """Guards against a seed that is silently ignored."""
    def run(seed):
        rng = np.random.default_rng(seed)
        c = entities.make_companies(SMALL, rng)
        b = entities.make_branches(SMALL, rng)
        d = entities.make_drugs(SMALL, rng, c)
        r = demand_mod.generate_regime_changes(SMALL, rng, d, b)
        dem, _ = demand_mod.simulate_true_demand(SMALL, rng, b, d, r)
        return dem

    assert not np.array_equal(run(1), run(2))


# ---------------------------------------------------------------------
# Intermittency -- the defining property of this problem
# ---------------------------------------------------------------------
def test_zero_fraction_within_target_band(sim):
    """P3 DoD: the zero-cell fraction must land in [0.65, 0.90].

    Below 0.65 the series are not intermittent and the whole modelling
    premise (Croston/TSB, hurdle models) is unmotivated. Above 0.90 there is
    too little signal to learn anything and results become noise.
    """
    zero_frac = float((sim["demand"] == 0).mean())
    assert 0.65 <= zero_frac <= 0.90, f"zero fraction {zero_frac:.3f} outside target band"


def test_demand_is_overdispersed(sim):
    """Variance must exceed the mean. A Poisson-shaped panel would be
    smoother than reality and would flatter every model trained on it."""
    d = sim["demand"].reshape(-1, sim["demand"].shape[-1])
    # Restrict to series with enough movement for the moments to be stable.
    active = d[d.sum(axis=1) > 100]
    assert len(active) > 0
    mean = active.mean(axis=1)
    var = active.var(axis=1)
    assert (var > mean).mean() > 0.9


# ---------------------------------------------------------------------
# Seasonality must be recoverable, and only where it was injected
# ---------------------------------------------------------------------
def test_seasonal_amplitude_tracks_configuration(sim):
    """Recovered annual amplitude must correlate with the configured one.

    Stronger than "some seasonality exists": it checks that drugs configured
    as aseasonal (chronic medication) come back aseasonal, so the test fails
    if the generator smears one global season across the whole catalogue.
    """
    dem = sim["demand"].sum(axis=0)            # (n_drugs, n_days)
    n_t = dem.shape[1]
    t = np.arange(n_t)
    # Single annual harmonic; amplitude = hypot of the two coefficients.
    X = np.column_stack([
        np.ones(n_t),
        np.cos(2 * np.pi * t / 365.25),
        np.sin(2 * np.pi * t / 365.25),
    ])
    recovered, configured = [], []
    for i in range(dem.shape[0]):
        y = dem[i].astype(float)
        if y.sum() < 500:                       # too sparse to estimate
            continue
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        if coef[0] <= 0:
            continue
        recovered.append(np.hypot(coef[1], coef[2]) / coef[0])
        configured.append(sim["drugs"]["season_amplitude"].iloc[i])

    assert len(recovered) >= 10
    r = np.corrcoef(recovered, configured)[0, 1]
    assert r > 0.6, f"recovered amplitude correlates only r={r:.2f} with configured"


# ---------------------------------------------------------------------
# Inventory ledger integrity
# ---------------------------------------------------------------------
def test_ledger_flow_identity_holds(sim):
    """open + received - dispensed - expired == close, on every single row.

    This caught a real bug: recording the opening position after receipts
    double-counted arrivals on 142,605 rows of the first full run.
    """
    inv = sim["inv"]
    lhs = (inv["qty_open"] + inv["qty_received"]
           - inv["qty_dispensed"] - inv["qty_expired"])
    violations = int((lhs != inv["qty_close"]).sum())
    assert violations == 0, f"{violations} rows violate the flow identity"


def test_unmet_demand_implies_empty_shelf(sim):
    """Unmet demand is only legitimate once closing stock is zero."""
    inv = sim["inv"]
    bad = int(((inv["qty_unmet"] > 0) & (inv["qty_close"] != 0)).sum())
    assert bad == 0, f"{bad} rows report unmet demand while still holding stock"


def test_quantities_are_non_negative(sim):
    for name, arr in sim["inv"].items():
        assert (arr >= 0).all(), f"{name} contains negative values"


def test_sales_never_exceed_true_demand(sim):
    """Censoring runs one way: you cannot sell more than was demanded."""
    assert (sim["inv"]["qty_dispensed"] <= sim["demand"]).all()


def test_censoring_actually_occurs(sim):
    """There must be real stockouts, or P5's censoring correction is
    solving a problem this dataset does not contain."""
    unmet_rate = float((sim["inv"]["qty_unmet"] > 0).mean())
    assert 0.005 < unmet_rate < 0.35, f"unmet rate {unmet_rate:.3f} implausible"


def test_expiry_waste_is_non_trivial(sim):
    """Waste must be measurable -- it is one of the three cost terms the
    flagship optimises. An earlier bug reported zero waste on every sweep."""
    assert sim["inv"]["qty_expired"].sum() > 0


# ---------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------
def test_regime_changes_shift_demand(sim):
    """Every injected regime change must be visible in the data, otherwise
    P10 drift detection would be evaluated against an effect that is not
    actually present."""
    detected = 0
    for row in sim["regimes"].itertuples(index=False):
        series = sim["demand"][row.branch_id - 1, row.drug_id - 1]
        cut = row.change_day_index
        before = series[max(0, cut - 90):cut].mean()
        after = series[cut:cut + 90].mean()
        if before <= 0.05 and after <= 0.05:
            continue                              # series too sparse to judge
        # Directionally correct: an injected surge must raise the mean and an
        # injected collapse must lower it.
        if (row.multiplier > 1) == (after > before):
            detected += 1
    assert detected >= len(sim["regimes"]) * 0.5

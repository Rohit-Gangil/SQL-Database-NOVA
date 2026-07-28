"""Equivalence tests: vectorised baselines must match the reference loops.

The per-series implementations in `baselines.py` are the reference: readable and
obviously correct. The `*_batch` forms are the ones the backtest actually runs.
These tests exist so the speedup cannot silently change a number -- which is the
usual way an optimisation corrupts results.

Regression guard for audit item m-3.
"""

from __future__ import annotations

import numpy as np
import pytest

from nova.forecast import baselines


@pytest.fixture(scope="module")
def panel() -> np.ndarray:
    """A panel spanning the awkward cases, not just the easy ones."""
    rng = np.random.default_rng(17)
    n_s, n_d = 60, 300
    out = np.zeros((n_s, n_d))
    for i in range(n_s):
        if i % 12 == 0:
            continue                                   # all-zero series
        rate = rng.uniform(0.02, 0.8)                  # sparse .. dense
        occ = rng.random(n_d) < rate
        out[i] = occ * rng.integers(1, 9, size=n_d)
    # A series that sells then dies -- the case TSB exists to handle.
    out[1, 150:] = 0
    # A series that starts late.
    out[2, :200] = 0
    return out


HORIZON = 14


def _reference(panel: np.ndarray, fn, **kw) -> np.ndarray:
    return np.vstack([fn(panel[i], HORIZON, **kw) for i in range(panel.shape[0])])


def test_naive_batch_matches_reference(panel):
    np.testing.assert_allclose(
        baselines.naive_batch(panel, HORIZON), _reference(panel, baselines.naive)
    )


def test_seasonal_naive_batch_matches_reference(panel):
    np.testing.assert_allclose(
        baselines.seasonal_naive_batch(panel, HORIZON, 7),
        _reference(panel, baselines.seasonal_naive, period=7),
    )


def test_mean_batch_matches_reference(panel):
    np.testing.assert_allclose(
        baselines.mean_batch(panel, HORIZON, 28),
        _reference(panel, baselines.mean_forecast, window=28),
    )


@pytest.mark.parametrize("variant", ["croston", "sba", "tsb"])
def test_croston_batch_matches_reference(panel, variant):
    got = baselines.croston_batch(panel, HORIZON, variant=variant)
    want = _reference(panel, baselines.croston, variant=variant)
    np.testing.assert_allclose(got, want, rtol=1e-9, atol=1e-9)


def test_all_zero_series_forecast_zero(panel):
    """A dead series must forecast zero under every method, or the inventory
    policy will stock an item nobody buys."""
    dead = np.zeros((3, 120))
    for fn in (baselines.naive_batch, baselines.seasonal_naive_batch,
               baselines.mean_batch):
        assert fn(dead, HORIZON).sum() == 0
    for v in ("croston", "sba", "tsb"):
        assert baselines.croston_batch(dead, HORIZON, variant=v).sum() == 0


def test_batch_is_actually_faster(panel):
    """Guards the reason this code exists. If the vectorised form is not
    faster, it is pure added risk and should be deleted."""
    import time

    big = np.repeat(panel, 8, axis=0)          # 480 series
    t0 = time.perf_counter()
    _reference(big, baselines.croston, variant="sba")
    ref_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    baselines.croston_batch(big, HORIZON, variant="sba")
    bat_s = time.perf_counter() - t0

    assert bat_s < ref_s, f"vectorised {bat_s:.3f}s not faster than reference {ref_s:.3f}s"

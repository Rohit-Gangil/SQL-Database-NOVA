"""Rungs 0 and 1 of the model ladder: naive and classical intermittent methods.

Every rung must be beaten by the next, or the failure to beat it gets reported.
A forecasting project without a naive floor is unfalsifiable.

Croston (1972) is the foundation for intermittent demand: rather than smoothing
the series directly -- which drags a zero-heavy series toward zero -- it smooths
the *demand size* and the *inter-demand interval* separately and divides one by
the other. SBA (Syntetos-Boylan Approximation) corrects Croston's known positive
bias by a factor of (1 - alpha/2). TSB (Teunter-Syntetos-Babai) updates the
demand *probability* rather than the interval, which makes it the only one of
the three that decays sensibly when an item stops selling -- important here,
because ~8% of the catalogue is discontinued mid-window.
"""

from __future__ import annotations

import numpy as np


def naive(history: np.ndarray, horizon: int) -> np.ndarray:
    """Repeat the last observation. The absolute floor."""
    last = history[-1] if len(history) else 0.0
    return np.full(horizon, float(last))


def seasonal_naive(history: np.ndarray, horizon: int, period: int = 7) -> np.ndarray:
    """Repeat the value from one seasonal period ago.

    For daily pharmacy data the weekly cycle is the strong one, so period=7.
    This is the baseline that most naive point forecasts actually lose to.
    """
    if len(history) < period:
        return naive(history, horizon)
    season = history[-period:]
    return np.array([season[i % period] for i in range(horizon)], dtype=float)


def mean_forecast(history: np.ndarray, horizon: int, window: int = 28) -> np.ndarray:
    """Trailing mean. Surprisingly hard to beat on lumpy series."""
    w = history[-window:] if len(history) >= window else history
    return np.full(horizon, float(w.mean()) if len(w) else 0.0)


def croston(history: np.ndarray, horizon: int, alpha: float = 0.1,
            variant: str = "sba") -> np.ndarray:
    """Croston / SBA / TSB forecast of demand per period.

    Returns a flat forecast: all three methods produce a single rate, which is
    correct -- they model the *rate* of demand, not its timing.

    variant:
        "croston" -- original, known to be positively biased
        "sba"     -- Syntetos-Boylan bias correction, (1 - alpha/2)
        "tsb"     -- Teunter-Syntetos-Babai, updates probability not interval
    """
    nz = np.flatnonzero(history)
    if len(nz) == 0:
        return np.zeros(horizon)

    if variant == "tsb":
        # Probability of demand occurring, updated every period (including
        # zeros) -- this is what lets TSB decay toward zero for dead items.
        p = 1.0 / max(1.0, float(np.mean(np.diff(nz))) if len(nz) > 1 else 1.0)
        z = float(history[nz[0]])
        for t in range(len(history)):
            if history[t] > 0:
                z += alpha * (history[t] - z)
                p += alpha * (1.0 - p)
            else:
                p += alpha * (0.0 - p)
        return np.full(horizon, z * p)

    # Croston / SBA: smooth size and interval separately.
    z = float(history[nz[0]])          # demand size
    x = float(nz[0] + 1)               # inter-demand interval
    last = nz[0]
    for t in nz[1:]:
        z += alpha * (history[t] - z)
        x += alpha * ((t - last) - x)
        last = t

    rate = z / x if x > 0 else 0.0
    if variant == "sba":
        rate *= (1.0 - alpha / 2.0)
    return np.full(horizon, rate)


# =====================================================================
# Vectorised forms.
#
# The per-series functions above are the reference implementation: readable,
# obviously correct, and slow. Looping them over 5,400 series x 6 origins cost
# ~20 minutes per backtest, which made every downstream fix expensive to
# validate.
#
# These run the same recursions with all series as a vector, looping only over
# time. tests/test_baselines_vectorised.py asserts they agree with the
# reference implementations to floating-point tolerance -- the reference stays
# in the file precisely so that equivalence can be tested rather than assumed.
# =====================================================================


def naive_batch(hist: np.ndarray, horizon: int) -> np.ndarray:
    """hist: (n_series, n_days) -> (n_series, horizon)"""
    last = hist[:, -1] if hist.shape[1] else np.zeros(hist.shape[0])
    return np.repeat(last[:, None], horizon, axis=1).astype(float)


def seasonal_naive_batch(hist: np.ndarray, horizon: int, period: int = 7) -> np.ndarray:
    n_s, n_d = hist.shape
    if n_d < period:
        return naive_batch(hist, horizon)
    season = hist[:, -period:]
    idx = np.arange(horizon) % period
    return season[:, idx].astype(float)


def mean_batch(hist: np.ndarray, horizon: int, window: int = 28) -> np.ndarray:
    w = hist[:, -window:] if hist.shape[1] >= window else hist
    m = w.mean(axis=1) if w.shape[1] else np.zeros(hist.shape[0])
    return np.repeat(m[:, None], horizon, axis=1).astype(float)


def croston_batch(hist: np.ndarray, horizon: int, alpha: float = 0.1,
                  variant: str = "sba") -> np.ndarray:
    """Vectorised Croston / SBA / TSB across series.

    Loops over time once, updating all series simultaneously. Series with no
    demand at all return zero, matching the reference implementation.
    """
    n_s, n_d = hist.shape
    h = hist.astype(float)
    has_any = (h > 0).any(axis=1)

    if variant == "tsb":
        # Index of the first non-zero, per series, for initialisation.
        first_nz = np.argmax(h > 0, axis=1)
        z = h[np.arange(n_s), first_nz].astype(float)
        # Initial probability from the mean inter-demand interval.
        nz_counts = (h > 0).sum(axis=1)
        span = n_d - first_nz
        p = np.where(nz_counts > 1, nz_counts / np.maximum(span, 1), 1.0).astype(float)
        for t in range(n_d):
            occurred = h[:, t] > 0
            z = np.where(occurred, z + alpha * (h[:, t] - z), z)
            p = np.where(occurred, p + alpha * (1.0 - p), p + alpha * (0.0 - p))
        rate = z * p
    else:
        first_nz = np.argmax(h > 0, axis=1)
        z = h[np.arange(n_s), first_nz].astype(float)
        x = (first_nz + 1).astype(float)
        last = first_nz.astype(float)
        for t in range(n_d):
            # Only periods strictly after the first non-zero update the state.
            occurred = (h[:, t] > 0) & (t > first_nz)
            gap = t - last
            z = np.where(occurred, z + alpha * (h[:, t] - z), z)
            x = np.where(occurred, x + alpha * (gap - x), x)
            last = np.where(occurred, float(t), last)
        rate = np.where(x > 0, z / np.maximum(x, 1e-12), 0.0)
        if variant == "sba":
            rate = rate * (1.0 - alpha / 2.0)

    rate = np.where(has_any, rate, 0.0)
    return np.repeat(rate[:, None], horizon, axis=1)


def empirical_quantiles(history: np.ndarray, horizon: int,
                        quantiles: tuple[float, ...],
                        window: int = 91) -> dict[float, np.ndarray]:
    """Quantiles of recent demand, used as the probabilistic baseline.

    The decision layer needs a distribution, not a point. This provides the
    dumbest possible one so that a learned quantile model has something honest
    to be compared against.
    """
    w = history[-window:] if len(history) >= window else history
    if len(w) == 0:
        return {q: np.zeros(horizon) for q in quantiles}
    return {q: np.full(horizon, float(np.quantile(w, q))) for q in quantiles}

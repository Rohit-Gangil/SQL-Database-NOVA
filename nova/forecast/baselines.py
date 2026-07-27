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

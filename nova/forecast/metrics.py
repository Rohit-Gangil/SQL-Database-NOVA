"""Forecast accuracy metrics.

Metric choice matters more than usual on intermittent data. MAPE is undefined
when the actual is zero -- which is ~74% of cells here -- so it is not used
anywhere in this project. WAPE and RMSSE are scale-free and defined on zeros.

Everything is evaluated against **true demand** from `nova_truth`, never against
observed sales. A model trained on censored sales that is then scored against
censored sales would look excellent while systematically under-forecasting.
"""

from __future__ import annotations

import numpy as np


def wape(actual: np.ndarray, pred: np.ndarray) -> float:
    """Weighted absolute percentage error: sum|e| / sum|actual|.

    The workhorse for intermittent demand. Defined at zero actuals, and it
    weights by volume, so being wrong about a fast mover counts more than
    being wrong about a dead SKU -- which is what the business cares about.
    """
    denom = np.abs(actual).sum()
    if denom == 0:
        return float("nan")
    return float(np.abs(actual - pred).sum() / denom)


def rmsse(actual: np.ndarray, pred: np.ndarray, insample: np.ndarray,
          period: int = 1) -> float:
    """Root mean squared scaled error (the M5 competition metric).

    Scales error by the in-sample naive error, making series comparable. NaN
    when the in-sample series is constant, which is correct: there is no
    meaningful scale to divide by.
    """
    if len(insample) <= period:
        return float("nan")
    scale = np.mean((insample[period:] - insample[:-period]) ** 2)
    if scale <= 0:
        return float("nan")
    return float(np.sqrt(np.mean((actual - pred) ** 2) / scale))


def bias(actual: np.ndarray, pred: np.ndarray) -> float:
    """Mean signed error, normalised by mean actual.

    Reported because on censored data the interesting failure is directional:
    a model trained on sales under-forecasts, and a single accuracy number
    hides that entirely.
    """
    denom = np.abs(actual).mean()
    if denom == 0:
        return float("nan")
    return float((pred - actual).mean() / denom)


def pinball_loss(actual: np.ndarray, pred: np.ndarray, q: float) -> float:
    """Quantile (pinball) loss. The correct scoring rule for a quantile forecast.

    Asymmetric by design: at q=0.9 under-prediction is penalised 9x more than
    over-prediction, which is exactly the asymmetry the inventory decision has.
    """
    e = actual - pred
    return float(np.mean(np.maximum(q * e, (q - 1) * e)))


def coverage(actual: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    """Empirical coverage of a prediction interval.

    A calibrated 90% interval should contain the truth ~90% of the time. This
    is the check that separates a probabilistic forecast from a point forecast
    wearing error bars.
    """
    return float(np.mean((actual >= lower) & (actual <= upper)))


def summarise(actual: np.ndarray, pred: np.ndarray,
              insample: np.ndarray | None = None) -> dict[str, float]:
    out = {
        "wape": wape(actual, pred),
        "bias": bias(actual, pred),
        "mae": float(np.mean(np.abs(actual - pred))),
        "rmse": float(np.sqrt(np.mean((actual - pred) ** 2))),
    }
    if insample is not None:
        out["rmsse"] = rmsse(actual, pred, insample)
    return out


def bootstrap_ci(values: np.ndarray, n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap CI over per-origin or per-series metric values.

    Reported so the baselines table carries error bars. A single point estimate
    of WAPE across one backtest origin says nothing about whether a difference
    between two models is real.
    """
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    boots = rng.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    return (float(np.quantile(boots, alpha / 2)),
            float(np.quantile(boots, 1 - alpha / 2)))

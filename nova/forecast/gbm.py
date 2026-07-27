"""Rung 2: a global gradient-boosted model over all series.

"Global" means one model learns across all 5,400 series rather than fitting
5,400 separate models. That is the design that actually scales, and it lets a
sparse SKU borrow strength from similar ones -- which is the only way a series
with eleven non-zero days in three years is forecastable at all.

Objective
---------
Tweedie, not squared error. The target is a non-negative count with a large
point mass at zero and a right skew; squared error assumes symmetric Gaussian
noise and will happily predict negative demand. Tweedie with 1 < p < 2 is a
compound Poisson-Gamma, which is *structurally* the right family for
"occasional arrivals of variable size" -- exactly Croston's decomposition,
learned rather than assumed.

Predictive distribution
-----------------------
The decision layer needs arbitrary quantiles per SKU, because each SKU's
critical ratio differs. Fitting a separate quantile model per required quantile
per origin was rejected on cost (docs/DECISIONS.md D-007): instead the point
forecast is treated as the mean of a negative binomial whose dispersion is
estimated from held-out residuals, and quantiles are read off analytically.
Whether that distributional assumption holds is not asserted -- it is tested,
by reporting empirical interval coverage in docs/RESULTS.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None

DEFAULT_PARAMS: dict = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.2,
    "metric": "tweedie",
    "learning_rate": 0.06,
    "num_leaves": 96,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "num_threads": 0,
    "verbosity": -1,
    "seed": 42,
}


def fit_gbm(train: pd.DataFrame, feature_cols: list[str], target_col: str,
            num_boost_round: int = 400,
            params: dict | None = None) -> lgb.Booster:
    if lgb is None:
        raise ImportError("lightgbm is required for rung 2")
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update(params)

    X = train[feature_cols]

    # LightGBM's own error for a non-numeric column is a DTypePromotionError
    # raised deep in dataset construction, which names no column. Fail here
    # instead, naming the offender.
    bad = [c for c in feature_cols
           if not pd.api.types.is_numeric_dtype(X[c])
           or pd.api.types.is_timedelta64_dtype(X[c])]
    if bad:
        raise TypeError(
            f"non-numeric feature column(s) passed to LightGBM: {bad}. "
            "Cast in the feature SQL -- DuckDB date arithmetic yields INTERVAL."
        )

    y = train[target_col].to_numpy(dtype=float)
    ds = lgb.Dataset(X, label=y, free_raw_data=True)
    return lgb.train(p, ds, num_boost_round=num_boost_round)


def predict_mean(model: lgb.Booster, frame: pd.DataFrame,
                 feature_cols: list[str]) -> np.ndarray:
    """Point forecast, clipped at zero. Negative demand is not a thing."""
    return np.clip(model.predict(frame[feature_cols]), 0.0, None)


def estimate_dispersion(actual: np.ndarray, mean_pred: np.ndarray) -> float:
    """Estimate negative-binomial dispersion k from held-out residuals.

    For NegBinom, Var = mu + mu^2 / k. Solving the method-of-moments estimate
    over the pooled sample:

        k = mean(mu^2) / max(mean((y - mu)^2 - mu), eps)

    Estimated on held-out data, never on the training fold, or the interval
    widths would inherit the model's in-sample optimism.
    """
    mu = np.clip(mean_pred, 1e-6, None)
    excess = np.mean((actual - mu) ** 2 - mu)
    if excess <= 0:
        return 1e6                     # effectively Poisson
    return float(np.mean(mu ** 2) / excess)


def nbinom_quantile(mean: np.ndarray, k: float, q: float | np.ndarray) -> np.ndarray:
    """Quantile of NegBinom(mean, dispersion k), vectorised over mean and q.

    scipy parameterises by (n, p) with mean = n(1-p)/p, so n = k and
    p = k / (k + mean).
    """
    mu = np.clip(mean, 1e-9, None)
    n = k
    p = n / (n + mu)
    return stats.nbinom.ppf(q, n, p)


def horizon_quantile(mean_daily: np.ndarray, k: float, q: float | np.ndarray,
                     days: int) -> np.ndarray:
    """Quantile of demand summed over `days`.

    Independent NegBinom days with common dispersion sum to a NegBinom with
    mean `days * mu` and dispersion `days * k`. Independence across days is an
    approximation -- real demand is autocorrelated -- and it is stated as a
    limitation rather than hidden, because it makes the interval slightly too
    narrow.
    """
    return nbinom_quantile(mean_daily * days, k * days, q)

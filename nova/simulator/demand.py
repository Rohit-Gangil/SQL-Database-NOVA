"""The demand-generating process.

True demand for (branch b, drug d, day t) is a negative-binomial draw:

    mu[b,d,t] = lambda[b,d]
                * annual(t; peak_doy[d], amp[d])
                * weekly(t; weekend_factor[b])
                * lifecycle(t; launch[d], discontinue[d])
                * regime(t; injected changes)
                * trend(t)

    demand[b,d,t] ~ NegBinom(mean=mu, dispersion=k)

Negative binomial rather than Poisson because real demand is overdispersed:
variance exceeds the mean. A Poisson assumption produces series that are too
smooth, which flatters every model trained on them.

`lambda[b,d]` is lognormal with a low median, which is what produces
intermittency -- most cells are zero because their rate is genuinely tiny, not
because zeros were sprinkled in afterwards.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nova.config import SimConfig


def _annual_factor(doy: np.ndarray, peak_doy: np.ndarray,
                   amplitude: np.ndarray) -> np.ndarray:
    """Annual seasonality, shape (n_drugs, n_days).

    Cosine peaking at `peak_doy`. Amplitude 0 leaves the series aseasonal,
    which is correct for chronic-disease medication.
    """
    phase = 2.0 * np.pi * (doy[None, :] - peak_doy[:, None]) / 365.25
    return 1.0 + amplitude[:, None] * np.cos(phase)


def _weekly_factor(dow: np.ndarray, weekend_factor: np.ndarray,
                   weekly_amplitude: float) -> np.ndarray:
    """Weekly seasonality, shape (n_branches, n_days).

    Mid-week is the trough, Friday/Saturday the peak, modulated per branch by
    its own weekend factor.
    """
    base = 1.0 + weekly_amplitude * np.cos(2.0 * np.pi * (dow[None, :] - 5) / 7.0)
    is_weekend = np.isin(dow, [5, 6])[None, :]
    return np.where(is_weekend, base * weekend_factor[:, None], base)


def _lifecycle_factor(cfg: SimConfig, drugs: pd.DataFrame) -> np.ndarray:
    """Product lifecycle, shape (n_drugs, n_days).

    Zero before launch, a 60-day ramp after it, zero after discontinuation.
    Produces a genuinely ragged panel: a model that assumes every series spans
    the full window will mis-handle roughly a fifth of the catalogue.
    """
    n_days = cfg.n_days
    t = np.arange(n_days)
    launch = drugs["launch_offset"].to_numpy()[:, None]
    disc = drugs["discontinue_offset"].to_numpy()[:, None]

    since_launch = t[None, :] - launch
    ramp = np.clip(since_launch / 60.0, 0.0, 1.0)
    alive = (since_launch >= 0)
    alive &= (disc < 0) | (t[None, :] < disc)
    return np.where(alive, ramp, 0.0)


def generate_regime_changes(cfg: SimConfig, rng: np.random.Generator,
                            drugs: pd.DataFrame,
                            branches: pd.DataFrame) -> pd.DataFrame:
    """Injected demand regime shifts -- ground truth for P10 drift detection.

    Confined to the last third of the window so they land in the backtest
    period, where a monitoring system would have to catch them.
    """
    n = cfg.n_regime_changes
    start = int(cfg.n_days * 0.62)
    return pd.DataFrame(
        {
            "regime_id": np.arange(1, n + 1, dtype=np.int32),
            "drug_id": rng.choice(drugs["drug_id"], size=n).astype(np.int32),
            "branch_id": rng.choice(branches["branch_id"], size=n).astype(np.int32),
            "change_day_index": rng.integers(start, cfg.n_days - 30, size=n).astype(np.int32),
            # Bimodal: collapses and surges, not gentle drifts, so detection
            # has an unambiguous answer.
            "multiplier": np.where(
                rng.random(n) < 0.5,
                rng.uniform(0.25, 0.55, size=n),
                rng.uniform(1.8, 3.2, size=n),
            ).round(3),
        }
    )


def simulate_true_demand(
    cfg: SimConfig,
    rng: np.random.Generator,
    branches: pd.DataFrame,
    drugs: pd.DataFrame,
    regimes: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (demand, mu) each shaped (n_branches, n_drugs, n_days).

    `mu` is retained because it is the irreducible-error floor: no forecaster
    can beat the conditional mean of the generating process. Reporting model
    error against that floor is more honest than reporting it against zero.
    """
    n_b, n_d, n_t = cfg.n_branches, cfg.n_drugs, cfg.n_days

    dates = pd.date_range(cfg.start_date, periods=n_t, freq="D")
    doy = dates.dayofyear.to_numpy()
    dow = dates.dayofweek.to_numpy()

    # --- Per-series base rate -----------------------------------------
    # Lognormal, modulated by branch scale and drug popularity. The
    # multiplicative branch x drug structure is what makes hierarchical
    # reconciliation meaningful later.
    log_rate = rng.normal(cfg.log_rate_mean, cfg.log_rate_sd, size=(n_b, n_d))
    lam = np.exp(log_rate)
    lam *= branches["scale"].to_numpy()[:, None]
    lam *= drugs["popularity"].to_numpy()[None, :]

    # --- Deterministic factors ----------------------------------------
    annual = _annual_factor(
        doy,
        drugs["season_peak_doy"].to_numpy(),
        drugs["season_amplitude"].to_numpy(),
    )                                                    # (n_d, n_t)
    weekly = _weekly_factor(dow, branches["weekend_factor"].to_numpy(),
                            cfg.weekly_amplitude)        # (n_b, n_t)
    lifecycle = _lifecycle_factor(cfg, drugs)            # (n_d, n_t)

    # Gentle chain-wide growth: +12% over three years.
    trend = 1.0 + 0.12 * (np.arange(n_t) / n_t)          # (n_t,)

    # --- Assemble mu ---------------------------------------------------
    # (n_b, n_d, n_t) float32: ~23 MB at the configured size.
    mu = (
        lam[:, :, None].astype(np.float32)
        * (annual * lifecycle)[None, :, :].astype(np.float32)
        * weekly[:, None, :].astype(np.float32)
        * trend[None, None, :].astype(np.float32)
    )

    # --- Injected regime changes --------------------------------------
    for row in regimes.itertuples(index=False):
        bi = row.branch_id - 1
        di = row.drug_id - 1
        mu[bi, di, row.change_day_index:] *= np.float32(row.multiplier)

    mu = np.clip(mu, 0.0, None)

    # --- Negative-binomial draw ---------------------------------------
    # Parameterised by mean mu and dispersion k: variance = mu + mu^2/k.
    # p = k / (k + mu); numpy's negative_binomial(n, p) has mean n(1-p)/p = mu.
    k = np.float32(cfg.size_dispersion)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = k / (k + mu)
    p = np.clip(p, 1e-6, 1.0 - 1e-9)

    demand = rng.negative_binomial(k, p).astype(np.int32)
    # Dead series produce no demand, regardless of the draw.
    demand[mu <= 0] = 0

    return demand, mu


def generate_supply_shocks(cfg: SimConfig, rng: np.random.Generator,
                           companies: pd.DataFrame,
                           drugs: pd.DataFrame) -> pd.DataFrame:
    """Manufacturer outages -- ground truth for honest error decomposition.

    A forecaster is not "wrong" for failing to anticipate a plant going
    offline. Recording shocks lets P6 separate error it could have avoided
    from error it could not.
    """
    n = cfg.n_supply_shocks
    # Less reliable manufacturers fail more often.
    w = (1.0 - companies["reliability"].to_numpy())
    w = w / w.sum()
    company_ids = rng.choice(companies["company_id"], size=n, p=w)

    starts = rng.integers(30, cfg.n_days - 40, size=n)
    durations = rng.integers(14, 31, size=n)
    return pd.DataFrame(
        {
            "shock_id": np.arange(1, n + 1, dtype=np.int32),
            "company_id": company_ids.astype(np.int32),
            "start_day_index": starts.astype(np.int32),
            "end_day_index": (starts + durations).astype(np.int32),
            "severity": rng.uniform(0.55, 1.0, size=n).round(3),
        }
    )

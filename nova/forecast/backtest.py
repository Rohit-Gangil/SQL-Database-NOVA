"""Rolling-origin backtest and the policy comparison.

    python -m nova.forecast.backtest

Produces docs/RESULTS.md. Every number in that file comes from this run; none
is written by hand.

Evaluation protocol
-------------------
* **Time-based splits only.** At each origin the model sees strictly earlier
  data. There is no random splitting anywhere.
* **Six rolling origins**, monthly from 2025-07-01, horizon 14 days. Multiple
  origins are what make the confidence intervals meaningful -- a single split
  cannot tell you whether a difference between models is real.
* **Scored against true demand** from `nova_truth`, never against observed
  sales. A model trained on censored sales and scored on censored sales looks
  excellent while systematically under-forecasting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from nova.config import ARTIFACT_DIR, DUCKDB_PATH, SPLIT
from nova.features.build import FEATURE_COLUMNS
from nova.forecast import baselines, gbm, metrics

TRAIN_SAMPLE_ROWS = 1_500_000


@dataclass
class SeriesIndex:
    """Maps (branch_id, drug_id) to a row of the demand matrices."""
    keys: pd.DataFrame          # branch_id, drug_id, row
    dates: pd.DatetimeIndex

    def date_pos(self, d) -> int:
        return int(self.dates.get_loc(pd.Timestamp(d)))


def load_matrices(con) -> tuple[np.ndarray, np.ndarray, SeriesIndex, pd.DataFrame]:
    """Load true and observed demand as (n_series, n_days) matrices."""
    keys = con.execute("""
        SELECT branch_id, drug_id,
               ROW_NUMBER() OVER (ORDER BY branch_id, drug_id) - 1 AS row
        FROM mart.dim_series ORDER BY branch_id, drug_id
    """).df()
    dates = pd.DatetimeIndex(
        con.execute("SELECT DISTINCT date_key FROM mart.dim_date ORDER BY 1")
        .df()["date_key"]
    )

    obs = con.execute("""
        SELECT branch_id, drug_id, date_key, units_demanded_observed
        FROM mart.fct_demand_daily ORDER BY branch_id, drug_id, date_key
    """).df()
    truth = con.execute("""
        SELECT branch_id, drug_id, as_of_date AS date_key, demand_true
        FROM nova_truth.demand_true ORDER BY branch_id, drug_id, as_of_date
    """).df()

    n_s, n_t = len(keys), len(dates)
    observed = obs["units_demanded_observed"].to_numpy(dtype=np.float32).reshape(n_s, n_t)
    true = truth["demand_true"].to_numpy(dtype=np.float32).reshape(n_s, n_t)

    dim = con.execute("""
        SELECT s.branch_id, s.drug_id, s.mean_daily, s.demand_class,
               d.unit_cost, d.unit_margin, d.criticality, d.shelf_life_days,
               d.category, d.abc_tier
        FROM mart.dim_series s JOIN mart.dim_drug d USING (drug_id)
        ORDER BY s.branch_id, s.drug_id
    """).df()

    return true, observed, SeriesIndex(keys, dates), dim


# ---------------------------------------------------------------------
# Rungs 0-1: classical methods, computed per series from observed history
# ---------------------------------------------------------------------
def run_baselines(observed: np.ndarray, o_pos: int, horizon: int) -> dict[str, np.ndarray]:
    """Vectorised across series (audit m-3).

    The per-series reference implementations still live in `baselines.py` and
    `tests/test_baselines_vectorised.py` asserts these agree with them, so the
    speedup cannot silently change a reported number.
    """
    hist = observed[:, :o_pos]
    return {
        "naive": baselines.naive_batch(hist, horizon).astype(np.float32),
        "seasonal_naive": baselines.seasonal_naive_batch(hist, horizon, 7).astype(np.float32),
        "mean_28": baselines.mean_batch(hist, horizon, 28).astype(np.float32),
        "croston": baselines.croston_batch(hist, horizon, variant="croston").astype(np.float32),
        "sba": baselines.croston_batch(hist, horizon, variant="sba").astype(np.float32),
        "tsb": baselines.croston_batch(hist, horizon, variant="tsb").astype(np.float32),
    }


# ---------------------------------------------------------------------
# Rung 2: global LightGBM
# ---------------------------------------------------------------------
def _predict_window(con, model, lo: pd.Timestamp, hi: pd.Timestamp,
                    feature_cols: list[str], n_s: int) -> np.ndarray:
    """Predict over [lo, hi] and reshape to (n_series, n_days).

    The reshape assumes a complete rectangular panel. That is guaranteed by the
    ORDER BY plus the warehouse's no-date-gaps data-quality check, but it is
    asserted here anyway (audit m-2): a silent misalignment would corrupt every
    metric downstream while looking perfectly normal.
    """
    cols = ", ".join(feature_cols)
    frame = con.execute(f"""
        SELECT branch_id, drug_id, date_key, {cols}
        FROM mart.features
        WHERE date_key BETWEEN DATE '{lo.date()}' AND DATE '{hi.date()}'
        ORDER BY branch_id, drug_id, date_key
    """).df()

    n_days = (hi - lo).days + 1
    if len(frame) != n_s * n_days:
        raise ValueError(
            f"expected {n_s} x {n_days} = {n_s * n_days} rows for "
            f"[{lo.date()}, {hi.date()}], got {len(frame)}. The panel is not "
            "rectangular -- reshaping would silently misalign series."
        )
    preds = gbm.predict_mean(model, frame, feature_cols)
    return preds.astype(np.float32).reshape(n_s, n_days)


def run_gbm(con, origin: pd.Timestamp, horizon: int, target_col: str,
            idx: SeriesIndex, feature_cols: list[str],
            calib_days: int = 28) -> tuple[np.ndarray, np.ndarray, object]:
    """Returns (eval_preds, calibration_preds, model).

    The calibration predictions cover the `calib_days` immediately before the
    origin: after training (so out-of-sample) and before evaluation (so disjoint
    from what the intervals are scored on). Audit item M-2 -- dispersion was
    previously estimated on the evaluation window itself, which made any
    coverage figure optimistic by construction.
    """
    end = origin + pd.Timedelta(days=horizon - 1)
    cols = ", ".join(feature_cols)
    n_s = len(idx.keys)

    calib_lo = origin - pd.Timedelta(days=calib_days)
    calib_hi = origin - pd.Timedelta(days=1)

    train = con.execute(f"""
        SELECT {cols}, {target_col} AS y
        FROM mart.features
        WHERE date_key < DATE '{calib_lo.date()}'
          AND lag_28 IS NOT NULL
        USING SAMPLE {TRAIN_SAMPLE_ROWS} ROWS (reservoir, 42)
    """).df()

    model = gbm.fit_gbm(train, feature_cols, "y")

    eval_preds = _predict_window(con, model, origin, end, feature_cols, n_s)
    calib_preds = _predict_window(con, model, calib_lo, calib_hi, feature_cols, n_s)
    return eval_preds, calib_preds, model


# ---------------------------------------------------------------------
def evaluate(actual: np.ndarray, pred: np.ndarray,
             insample: np.ndarray) -> dict[str, float]:
    return {
        "wape": metrics.wape(actual.ravel(), pred.ravel()),
        "bias": metrics.bias(actual.ravel(), pred.ravel()),
        "rmse": float(np.sqrt(np.mean((actual - pred) ** 2))),
        "rmsse": float(np.nanmean([
            metrics.rmsse(actual[i], pred[i], insample[i])
            for i in range(0, actual.shape[0], 7)      # subsample for speed
        ])),
    }


def evaluate_probabilistic(actual: np.ndarray, mean_pred: np.ndarray,
                           k: float) -> dict[str, float]:
    """Calibration and sharpness of the negative-binomial predictive distribution.

    Audit item C-2: `docs/RESULTS.md` claimed these were reported when nothing
    computed them. Coverage is the honest test of the distributional assumption
    -- if a nominal 90% interval does not contain the truth ~90% of the time, the
    assumption is wrong and the newsvendor quantiles that depend on it are wrong
    too. Whatever this says gets published.
    """
    a = actual.ravel()
    mu = mean_pred.ravel()
    out: dict[str, float] = {}

    for nominal, (lo_q, hi_q) in {80: (0.10, 0.90), 90: (0.05, 0.95)}.items():
        lo = gbm.nbinom_quantile(mu, k, lo_q)
        hi = gbm.nbinom_quantile(mu, k, hi_q)
        out[f"coverage_{nominal}"] = metrics.coverage(a, lo, hi)
        out[f"width_{nominal}"] = float(np.mean(hi - lo))

    for q in (0.5, 0.9):
        pred_q = gbm.nbinom_quantile(mu, k, q)
        out[f"pinball_{int(q * 100)}"] = metrics.pinball_loss(a, pred_q, q)

    return out


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH), read_only=False)

    t0 = time.perf_counter()
    true, observed, idx, dim = load_matrices(con)
    print(f"[backtest] matrices {true.shape} loaded in {time.perf_counter()-t0:.1f}s")

    horizon = SPLIT.horizon_days
    feature_cols = list(FEATURE_COLUMNS)

    per_origin: list[dict] = []
    gbm_preds_by_origin: dict[pd.Timestamp, np.ndarray] = {}
    truth_by_origin: dict[pd.Timestamp, np.ndarray] = {}
    dispersion_samples: list[float] = []

    calib_days = 28

    for origin in SPLIT.backtest_origins:
        o = pd.Timestamp(origin)
        o_pos = idx.date_pos(o)
        actual = true[:, o_pos:o_pos + horizon]
        insample = observed[:, :o_pos]
        truth_by_origin[o] = actual

        t1 = time.perf_counter()
        base = run_baselines(observed, o_pos, horizon)

        # Trained on censored observations -- all a real system would have.
        gbm_pred, gbm_calib, _model = run_gbm(
            con, o, horizon, "units_demanded_censored", idx, feature_cols, calib_days
        )
        gbm_preds_by_origin[o] = gbm_pred

        # Trained on raw sales: the naive pipeline that ignores censoring.
        gbm_sold, _, _ = run_gbm(con, o, horizon, "units_sold", idx, feature_cols,
                                 calib_days)

        # Dispersion from the CALIBRATION window: after training, before
        # evaluation. Estimating it on the evaluation window (as an earlier
        # version did) makes coverage optimistic by construction -- audit M-2.
        calib_actual = true[:, o_pos - calib_days:o_pos]
        k_origin = gbm.estimate_dispersion(calib_actual.ravel(), gbm_calib.ravel())
        dispersion_samples.append(k_origin)

        row: dict = {"origin": o.date().isoformat(), "dispersion_k": k_origin}
        row.update(evaluate_probabilistic(actual, gbm_pred, k_origin))
        for name, pred in {**base,
                           "lightgbm": gbm_pred,
                           "lightgbm_sales_only": gbm_sold}.items():
            m = evaluate(actual, pred, insample)
            for k, v in m.items():
                row[f"{name}__{k}"] = v

        # The irreducible-error floor: the generating process's own conditional
        # mean. No forecaster can beat this, so it bounds what is achievable.
        mu = con.execute(f"""
            SELECT mu_true FROM nova_truth.demand_true
            WHERE as_of_date BETWEEN DATE '{o.date()}'
              AND DATE '{(o + pd.Timedelta(days=horizon-1)).date()}'
            ORDER BY branch_id, drug_id, as_of_date
        """).df()["mu_true"].to_numpy(dtype=np.float32).reshape(len(idx.keys), horizon)
        m = evaluate(actual, mu, insample)
        for k, v in m.items():
            row[f"oracle_mu__{k}"] = v

        per_origin.append(row)
        print(f"[backtest] origin {o.date()}  "
              f"snaive={row['seasonal_naive__wape']:.4f} "
              f"sba={row['sba__wape']:.4f} "
              f"lgbm={row['lightgbm__wape']:.4f} "
              f"floor={row['oracle_mu__wape']:.4f}  "
              f"cov90={row['coverage_90']:.3f} k={row['dispersion_k']:.2f}  "
              f"({time.perf_counter()-t1:.1f}s)")

    results = pd.DataFrame(per_origin)
    results.to_csv(ARTIFACT_DIR / "backtest_per_origin.csv", index=False)

    k_hat = float(np.median(dispersion_samples))
    print(f"[backtest] NegBinom dispersion k = {k_hat:.3f}")

    np.save(ARTIFACT_DIR / "gbm_preds.npy",
            np.stack([gbm_preds_by_origin[pd.Timestamp(o)] for o in SPLIT.backtest_origins]))
    np.save(ARTIFACT_DIR / "truth.npy",
            np.stack([truth_by_origin[pd.Timestamp(o)] for o in SPLIT.backtest_origins]))
    dim.to_parquet(ARTIFACT_DIR / "dim.parquet")
    with open(ARTIFACT_DIR / "dispersion.txt", "w") as f:
        f.write(str(k_hat))

    print(f"[backtest] done in {time.perf_counter()-t0:.1f}s "
          f"-> {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()

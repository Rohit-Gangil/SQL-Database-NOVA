"""Leakage tests — the P5 Definition of Done.

If these fail, every metric in docs/RESULTS.md is fiction. They are written to
be adversarial against my own feature SQL rather than to confirm it.

The central test is **future-perturbation invariance**: corrupt the target at
every date on or after a cutoff, rebuild the features, and assert that feature
values *before* the cutoff are bit-identical. Any feature reaching forward in
time changes, and the test fails.

A passing invariance test is not sufficient on its own -- features that are all
NULL would also pass -- so `test_perturbation_is_actually_detectable` proves the
instrument works by showing the same perturbation *does* move later rows.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

from nova.config import SPLIT
from nova.features.build import LAG, LAG_DAYS, ROLL_WINDOWS, feature_sql

N_BRANCHES, N_DRUGS, N_DAYS = 3, 4, 400
CUTOFF = pd.Timestamp("2023-01-01") + pd.Timedelta(days=300)


def _make_db(perturb_from: pd.Timestamp | None = None) -> pd.DataFrame:
    """Build a miniature mart and run the real feature SQL over it.

    The same `feature_sql()` used in production is exercised here; a
    reimplementation would test the wrong thing.
    """
    rng = np.random.default_rng(11)
    dates = pd.date_range("2023-01-01", periods=N_DAYS, freq="D")

    rows = []
    for b in range(1, N_BRANCHES + 1):
        for d in range(1, N_DRUGS + 1):
            sold = rng.poisson(1.2, size=N_DAYS)
            unmet = (rng.random(N_DAYS) < 0.05) * rng.poisson(1.0, size=N_DAYS)
            rows.append(pd.DataFrame({
                "branch_id": b, "drug_id": d, "date_key": dates,
                "units_sold": sold, "units_unmet": unmet,
            }))
    df = pd.concat(rows, ignore_index=True)
    df["units_demanded_observed"] = df["units_sold"] + df["units_unmet"]

    if perturb_from is not None:
        # A large, unmistakable corruption of the future.
        mask = df["date_key"] >= perturb_from
        df.loc[mask, "units_sold"] *= 1000
        df.loc[mask, "units_demanded_observed"] *= 1000

    df["is_censored"] = df["units_unmet"] > 0
    df["is_stocked_out"] = False
    df["qty_close"] = 5

    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA mart")
    con.register("_f", df)
    con.execute("CREATE TABLE mart.fct_demand_daily AS SELECT * FROM _f")

    con.execute("""
        CREATE TABLE mart.dim_branch AS
        SELECT DISTINCT branch_id,
               'B' || branch_id AS code, 'n' AS name,
               CASE WHEN branch_id % 2 = 0 THEN 'North' ELSE 'South' END AS region,
               'c' AS city, 1.0 AS scale, 1.0 AS weekend_factor
        FROM mart.fct_demand_daily
    """)
    con.execute("""
        CREATE TABLE mart.dim_drug AS
        SELECT DISTINCT drug_id, 'D' || drug_id AS trade_name, 1 AS company_id,
               'c' AS company_name, 'antibiotic' AS category,
               3 AS criticality, false AS is_controlled, 'tablet' AS dosage_form,
               10 AS pack_size, 20.0 AS unit_cost, 30.0 AS sale_price,
               10.0 AS unit_margin, 365 AS shelf_life_days, 1 AS abc_tier
        FROM mart.fct_demand_daily
    """)
    con.execute("""
        CREATE TABLE mart.dim_date AS
        SELECT DISTINCT date_key,
               EXTRACT(year FROM date_key)::SMALLINT AS year,
               EXTRACT(month FROM date_key)::SMALLINT AS month,
               EXTRACT(day FROM date_key)::SMALLINT AS day_of_month,
               EXTRACT(dayofweek FROM date_key)::SMALLINT AS day_of_week,
               EXTRACT(doy FROM date_key)::SMALLINT AS day_of_year,
               EXTRACT(week FROM date_key)::SMALLINT AS iso_week,
               (EXTRACT(dayofweek FROM date_key) IN (0,6)) AS is_weekend,
               DATE_TRUNC('month', date_key) AS month_start
        FROM mart.fct_demand_daily
    """)

    con.execute(feature_sql())
    out = con.execute("SELECT * FROM mart.features ORDER BY branch_id, drug_id, date_key").df()
    con.close()
    return out


@pytest.fixture(scope="module")
def clean() -> pd.DataFrame:
    return _make_db(perturb_from=None)


@pytest.fixture(scope="module")
def perturbed() -> pd.DataFrame:
    return _make_db(perturb_from=CUTOFF)


# Columns derived from the target. Static attributes and calendar terms are
# excluded because they cannot leak by construction.
DERIVED = (
    [f"lag_{d}" for d in LAG_DAYS]
    + [f"roll_mean_{w}" for w in ROLL_WINDOWS]
    + [f"roll_sd_{w}" for w in ROLL_WINDOWS]
    + [f"nonzero_rate_{w}" for w in ROLL_WINDOWS]
    + ["days_since_last_sale", "region_lag", "national_lag"]
)


def test_features_before_cutoff_are_invariant_to_future(clean, perturbed):
    """THE leakage test.

    Corrupting every target value on or after CUTOFF must not change a single
    feature value strictly before CUTOFF. Any feature that reads forward in
    time moves here.
    """
    a = clean[clean["date_key"] < CUTOFF].reset_index(drop=True)
    b = perturbed[perturbed["date_key"] < CUTOFF].reset_index(drop=True)
    assert len(a) == len(b) > 0

    offenders = []
    for col in DERIVED:
        va, vb = a[col].to_numpy(dtype="float64"), b[col].to_numpy(dtype="float64")
        both_nan = np.isnan(va) & np.isnan(vb)
        if not np.allclose(va[~both_nan], vb[~both_nan], equal_nan=True):
            n = int((~np.isclose(va, vb, equal_nan=True)).sum())
            offenders.append(f"{col} ({n} rows differ)")

    assert not offenders, "features leak future information: " + ", ".join(offenders)


def test_perturbation_is_actually_detectable(clean, perturbed):
    """Proves the instrument works.

    Without this, `test_features_before_cutoff_are_invariant_to_future` would
    pass trivially if every feature were NULL or constant.
    """
    after = clean["date_key"] >= CUTOFF + pd.Timedelta(days=LAG + max(LAG_DAYS))
    a = clean[after]["lag_1"].to_numpy(dtype="float64")
    b = perturbed[perturbed["date_key"] >= CUTOFF + pd.Timedelta(days=LAG + max(LAG_DAYS))]["lag_1"].to_numpy(dtype="float64")
    assert not np.allclose(a, b, equal_nan=True), \
        "perturbation had no effect anywhere -- the test cannot detect leakage"


def test_no_window_reaches_closer_than_the_availability_lag():
    """Static audit of the generated SQL.

    Every window bound must be at least LAG rows back. This catches a lag
    accidentally written as `LAG(x, 1)` when availability requires 2.
    """
    sql = feature_sql()
    assert LAG >= 1
    for d in LAG_DAYS:
        assert f"LAG(base.units_demanded_censored, {d + LAG})" in sql
    for w in ROLL_WINDOWS:
        assert f"{w + LAG - 1} PRECEDING AND {LAG} PRECEDING" in sql
    # Nothing may reference the current row in a target-derived window.
    assert "AND CURRENT ROW" not in sql


def test_target_column_is_not_among_the_features():
    """The target must not appear in its own feature list."""
    from nova.features.build import FEATURE_COLUMNS
    for forbidden in ("units_sold", "units_demanded_censored",
                      "units_demanded_observed", "is_censored"):
        assert forbidden not in FEATURE_COLUMNS


def test_backtest_origins_are_after_train_end():
    """Split sanity: no backtest origin may precede the end of training."""
    for origin in SPLIT.backtest_origins:
        assert origin > SPLIT.train_end

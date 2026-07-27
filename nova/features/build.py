"""Point-in-time-correct feature construction.

Two rules govern everything in this module, and every metric downstream is
worthless if either is broken:

**Rule 1 -- availability lag.** A feature computed for date *T* may only read
records with `date_key <= T - LAG`, where `LAG = SPLIT.feature_lag_days`.
Yesterday's sales are not in the warehouse at 00:00 today. Using `lag(1)` when
the true availability is `lag(2)` is invisible in a backtest and catastrophic
in production.

**Rule 2 -- target isolation.** The target for date *T* is drawn from a window
strictly after every feature's read window. `tests/test_leakage.py` shifts the
target and asserts feature values do not move.

On censoring
------------
`units_sold` is what a naive pipeline trains on, and it is wrong: on a stockout
day it records low demand when demand was in fact high. `units_demanded_censored`
adds back the unmet units the counter recorded. Neither equals true demand --
some patients leave without asking -- but the gap between the two is measurable,
and P6 reports it as an ablation rather than assuming the correction helps.
"""

from __future__ import annotations

import duckdb

from nova.config import SPLIT

LAG = SPLIT.feature_lag_days

# Every window below is expressed in days and offset by LAG. They are defined
# as data, not inlined into the SQL string, so the leakage test can assert
# that no window reaches closer to T than LAG.
LAG_DAYS: tuple[int, ...] = (1, 2, 3, 7, 14, 28)
ROLL_WINDOWS: tuple[int, ...] = (7, 28, 91)


def feature_sql(target_col: str = "units_demanded_censored") -> str:
    """SQL building the modelling table.

    `target_col` selects the training signal: `units_sold` reproduces the
    naive pipeline, `units_demanded_censored` the corrected one. Both are
    evaluated against true demand, which neither may be trained on.
    """
    lag_cols = ",\n".join(
        f"        LAG(base.{target_col}, {d + LAG}) OVER w AS lag_{d}"
        for d in LAG_DAYS
    )
    roll_cols = ",\n".join(
        f"""        AVG(base.{target_col})  OVER (w ROWS BETWEEN {w + LAG - 1} PRECEDING AND {LAG} PRECEDING) AS roll_mean_{w},
        STDDEV_POP(base.{target_col}) OVER (w ROWS BETWEEN {w + LAG - 1} PRECEDING AND {LAG} PRECEDING) AS roll_sd_{w},
        SUM(CASE WHEN base.{target_col} > 0 THEN 1 ELSE 0 END)
            OVER (w ROWS BETWEEN {w + LAG - 1} PRECEDING AND {LAG} PRECEDING)::DOUBLE / {w} AS nonzero_rate_{w}"""
        for w in ROLL_WINDOWS
    )

    return f"""
CREATE OR REPLACE TABLE mart.features AS
WITH base AS (
    SELECT
        f.branch_id, f.drug_id, f.date_key,
        f.units_sold,
        f.units_demanded_observed AS units_demanded_censored,
        f.is_censored, f.is_stocked_out, f.qty_close
    FROM mart.fct_demand_daily f
),
-- Hierarchy aggregates are lagged exactly like the series itself. An
-- unlagged regional total would carry same-day information from sibling
-- branches -- a subtle, common, and fatal leak.
--
-- The LAG must be applied HERE, at the (region, drug, date) grain where each
-- date appears exactly once. An earlier version aggregated here and lagged
-- after joining back to the branch-level rows; that partition contains one
-- row per branch per date, so LAG(1) returned an arbitrary sibling branch's
-- row from the SAME date rather than the previous date -- leaking today's
-- regional demand into today's features. tests/test_leakage.py caught it on
-- 482 region_lag rows and 2,078 national_lag rows.
regional AS (
    SELECT b.region, f.drug_id, f.date_key,
           SUM(f.{target_col}) AS region_units
    FROM base f JOIN mart.dim_branch b USING (branch_id)
    GROUP BY 1, 2, 3
),
regional_lagged AS (
    SELECT region, drug_id, date_key,
           LAG(region_units, {LAG}) OVER (
               PARTITION BY region, drug_id ORDER BY date_key) AS region_lag
    FROM regional
),
national AS (
    SELECT drug_id, date_key, SUM({target_col}) AS national_units
    FROM base GROUP BY 1, 2
),
national_lagged AS (
    SELECT drug_id, date_key,
           LAG(national_units, {LAG}) OVER (
               PARTITION BY drug_id ORDER BY date_key) AS national_lag
    FROM national
),
windowed AS (
    SELECT
        base.branch_id, base.drug_id, base.date_key,
        base.units_sold,
        base.units_demanded_censored,
        base.is_censored,
{lag_cols},
{roll_cols},
        -- Days since the last non-zero sale: the single most informative
        -- feature for intermittent series, and what Croston implicitly models.
        --
        -- DATE_DIFF, not date subtraction: in DuckDB `date - date` yields an
        -- INTERVAL, which arrives in pandas as timedelta64 and makes LightGBM
        -- fail with a DTypePromotionError rather than a useful message.
        DATE_DIFF('day',
            MAX(CASE WHEN base.{target_col} > 0 THEN base.date_key END)
                OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND {LAG} PRECEDING),
            base.date_key)::INTEGER
            AS days_since_last_sale,
        -- Recent stockout pressure: a series that has been stocking out is
        -- one whose observed history understates demand.
        AVG(CASE WHEN base.is_censored THEN 1.0 ELSE 0.0 END)
            OVER (w ROWS BETWEEN {28 + LAG - 1} PRECEDING AND {LAG} PRECEDING)
            AS censored_rate_28
    FROM base
    WINDOW w AS (PARTITION BY base.branch_id, base.drug_id ORDER BY base.date_key)
)
SELECT
    w.*,
    -- Calendar features: deterministic functions of the date, so they carry
    -- no leakage risk. A model may legitimately know next Tuesday is a Tuesday.
    dd.day_of_week, dd.day_of_year, dd.month, dd.is_weekend,
    SIN(2 * PI() * dd.day_of_year / 365.25)      AS doy_sin,
    COS(2 * PI() * dd.day_of_year / 365.25)      AS doy_cos,
    SIN(2 * PI() * dd.day_of_week / 7.0)         AS dow_sin,
    COS(2 * PI() * dd.day_of_week / 7.0)         AS dow_cos,
    -- Static attributes: known before the fact, no lag required.
    dr.category, dr.criticality, dr.abc_tier, dr.pack_size,
    dr.unit_cost, dr.unit_margin, dr.shelf_life_days, dr.is_controlled,
    br.region, br.scale AS branch_scale, br.weekend_factor,
    -- Lagged hierarchy context, already shifted at the correct grain above.
    rg.region_lag,
    nt.national_lag
FROM windowed w
JOIN mart.dim_date   dd ON dd.date_key = w.date_key
JOIN mart.dim_drug   dr USING (drug_id)
JOIN mart.dim_branch br USING (branch_id)
LEFT JOIN regional_lagged rg ON rg.region = br.region
                            AND rg.drug_id = w.drug_id
                            AND rg.date_key = w.date_key
LEFT JOIN national_lagged nt ON nt.drug_id = w.drug_id
                            AND nt.date_key = w.date_key
"""


FEATURE_COLUMNS: list[str] = (
    [f"lag_{d}" for d in LAG_DAYS]
    + [f"roll_mean_{w}" for w in ROLL_WINDOWS]
    + [f"roll_sd_{w}" for w in ROLL_WINDOWS]
    + [f"nonzero_rate_{w}" for w in ROLL_WINDOWS]
    + [
        "days_since_last_sale", "censored_rate_28",
        "day_of_week", "day_of_year", "month",
        "doy_sin", "doy_cos", "dow_sin", "dow_cos",
        "criticality", "abc_tier", "pack_size",
        "unit_cost", "unit_margin", "shelf_life_days",
        "branch_scale", "weekend_factor",
        "region_lag", "national_lag",
    ]
)

# Feature groups, for the P6 ablation study.
FEATURE_GROUPS: dict[str, list[str]] = {
    "lags": [f"lag_{d}" for d in LAG_DAYS],
    "rolling": (
        [f"roll_mean_{w}" for w in ROLL_WINDOWS]
        + [f"roll_sd_{w}" for w in ROLL_WINDOWS]
        + [f"nonzero_rate_{w}" for w in ROLL_WINDOWS]
    ),
    "intermittency": ["days_since_last_sale", "censored_rate_28"],
    "calendar": ["day_of_week", "day_of_year", "month",
                 "doy_sin", "doy_cos", "dow_sin", "dow_cos"],
    "product": ["criticality", "abc_tier", "pack_size", "unit_cost",
                "unit_margin", "shelf_life_days"],
    "branch": ["branch_scale", "weekend_factor"],
    "hierarchy": ["region_lag", "national_lag"],
}


def build_features(con: duckdb.DuckDBPyConnection,
                   target_col: str = "units_demanded_censored") -> int:
    con.execute(feature_sql(target_col))
    return con.execute("SELECT COUNT(*) FROM mart.features").fetchone()[0]

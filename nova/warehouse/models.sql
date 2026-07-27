-- =====================================================================
-- NOVA · Layer 2 · Analytics marts (DuckDB)
--
-- Star schema over the simulated OLTP data. Executed by
-- nova/warehouse/build.py in the order written.
--
-- Note on dbt: the plan (docs/PLAN.md P4) specified dbt for the model DAG.
-- These are the same models expressed as ordered SQL, executed directly,
-- to avoid adding a dependency that would not change the output. The
-- staging -> intermediate -> mart layering and the tests are preserved.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS mart;

-- ---------------------------------------------------------------------
-- dim_date. Calendar features are deterministic functions of the date and
-- therefore carry no leakage risk -- a model may legitimately know that
-- next Tuesday is a Tuesday.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.dim_date AS
SELECT
    d.as_of_date                                   AS date_key,
    EXTRACT(year   FROM d.as_of_date)::SMALLINT    AS year,
    EXTRACT(month  FROM d.as_of_date)::SMALLINT    AS month,
    EXTRACT(day    FROM d.as_of_date)::SMALLINT    AS day_of_month,
    EXTRACT(dayofweek FROM d.as_of_date)::SMALLINT AS day_of_week,
    EXTRACT(doy    FROM d.as_of_date)::SMALLINT    AS day_of_year,
    EXTRACT(week   FROM d.as_of_date)::SMALLINT    AS iso_week,
    (EXTRACT(dayofweek FROM d.as_of_date) IN (0, 6)) AS is_weekend,
    DATE_TRUNC('month', d.as_of_date)              AS month_start
FROM (SELECT DISTINCT as_of_date FROM nova.fact_demand) d;

-- ---------------------------------------------------------------------
-- dim_branch / dim_drug carry the forecasting hierarchy levels.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.dim_branch AS
SELECT branch_id, code, name, region, city, scale, weekend_factor
FROM nova.branch;

CREATE OR REPLACE TABLE mart.dim_drug AS
SELECT
    d.drug_id, d.trade_name, d.company_id, c.name AS company_name,
    d.category, d.criticality, d.is_controlled, d.dosage_form,
    d.pack_size, d.unit_cost, d.sale_price,
    d.sale_price - d.unit_cost                       AS unit_margin,
    d.shelf_life_days,
    -- ABC classification by revenue contribution: the standard inventory
    -- segmentation, and a useful model feature because A-items behave
    -- nothing like C-items.
    NTILE(3) OVER (ORDER BY d.unit_cost * d.popularity DESC) AS abc_tier
FROM nova.drug d
JOIN nova.company c USING (company_id);

-- ---------------------------------------------------------------------
-- fct_demand_daily: the grain the whole project forecasts on.
--
-- `units_demanded_observed` is deliberately named to make the censoring
-- explicit. It is dispensed + unmet, which is what a real chain could
-- reconstruct from its own records -- unmet is observable at the counter
-- ("we don't have it"), unlike true latent demand.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.fct_demand_daily AS
SELECT
    f.branch_id,
    f.drug_id,
    f.as_of_date                                   AS date_key,
    f.qty_dispensed                                AS units_sold,
    f.qty_unmet                                    AS units_unmet,
    f.qty_dispensed + f.qty_unmet                  AS units_demanded_observed,
    (f.qty_unmet > 0)                              AS is_censored,
    f.qty_open, f.qty_received, f.qty_expired, f.qty_close,
    f.reorder_point, f.qty_ordered,
    (f.qty_close = 0)                              AS is_stocked_out,
    f.qty_dispensed * d.sale_price                 AS revenue,
    f.qty_expired   * d.unit_cost                  AS waste_cost
FROM nova.fact_demand f
JOIN nova.drug d USING (drug_id);

-- ---------------------------------------------------------------------
-- Hierarchy rollups. The forecasting hierarchy is
--   (branch, drug) -> (region, drug) -> (national, drug)
-- and reconciliation requires the parents to be built from exactly the
-- same rows as the children, which is why they are derived here rather
-- than re-aggregated independently downstream.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.fct_demand_region AS
SELECT b.region, f.drug_id, f.date_key,
       SUM(f.units_demanded_observed) AS units_demanded_observed,
       SUM(f.units_sold)              AS units_sold
FROM mart.fct_demand_daily f
JOIN mart.dim_branch b USING (branch_id)
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE mart.fct_demand_national AS
SELECT f.drug_id, f.date_key,
       SUM(f.units_demanded_observed) AS units_demanded_observed,
       SUM(f.units_sold)              AS units_sold
FROM mart.fct_demand_daily f
GROUP BY 1, 2;

-- ---------------------------------------------------------------------
-- Series-level summary. Drives model selection: a series with 95% zeros
-- should not be handed to the same model as one that moves every day.
--
-- ADI (average demand interval) and CV^2 are the Syntetos-Boylan-Croston
-- classification axes: ADI >= 1.32 and CV^2 >= 0.49 marks "lumpy" demand,
-- the regime where classical exponential smoothing fails outright.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE mart.dim_series AS
WITH stats AS (
    SELECT
        branch_id, drug_id,
        COUNT(*)                                            AS n_days,
        SUM(units_demanded_observed)                        AS total_units,
        AVG(units_demanded_observed)                        AS mean_daily,
        STDDEV_POP(units_demanded_observed)                 AS sd_daily,
        SUM(CASE WHEN units_demanded_observed > 0 THEN 1 ELSE 0 END) AS n_nonzero,
        AVG(CASE WHEN is_censored THEN 1.0 ELSE 0.0 END)    AS censored_frac
    FROM mart.fct_demand_daily
    GROUP BY 1, 2
)
SELECT
    branch_id, drug_id, n_days, total_units, mean_daily, sd_daily,
    n_nonzero, censored_frac,
    CASE WHEN n_nonzero = 0 THEN NULL
         ELSE n_days::DOUBLE / n_nonzero END               AS adi,
    CASE WHEN mean_daily = 0 THEN NULL
         ELSE POWER(sd_daily / mean_daily, 2) END          AS cv2,
    CASE
        WHEN n_nonzero = 0                                       THEN 'dead'
        WHEN n_days::DOUBLE / n_nonzero <  1.32
         AND POWER(sd_daily / NULLIF(mean_daily,0), 2) <  0.49   THEN 'smooth'
        WHEN n_days::DOUBLE / n_nonzero <  1.32                  THEN 'erratic'
        WHEN POWER(sd_daily / NULLIF(mean_daily,0), 2) < 0.49    THEN 'intermittent'
        ELSE 'lumpy'
    END                                                    AS demand_class
FROM stats;

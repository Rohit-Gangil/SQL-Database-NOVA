-- =====================================================================
-- NOVA · Indexes
--
-- The original schema had zero indexes beyond those implied by primary
-- keys. Measured impact is in docs/PERF.md; every index below exists
-- because a specific query in this repo needed it, not by default.
-- =====================================================================

-- ---------------------------------------------------------------------
-- inventory_snapshot: the hot table. Two distinct access patterns.
-- ---------------------------------------------------------------------

-- (a) Time-series read for one series: "give me the history of drug D at
--     branch B". Served by the PK's leading columns already, so no extra
--     index is created for it -- noted here so the omission is deliberate.

-- (b) Cross-sectional read: "every series on date T", used by the daily
--     replenishment run and by every backtest origin. The PK cannot serve
--     this because as_of_date is its trailing column.
CREATE INDEX IF NOT EXISTS ix_snapshot_date
    ON nova.inventory_snapshot (as_of_date)
    INCLUDE (branch_id, drug_id, qty_close, qty_unmet);

-- (c) Stockout analysis. Partial index: unmet demand is rare by
--     construction, so indexing only the non-zero rows keeps this ~2
--     orders of magnitude smaller than a full index.
CREATE INDEX IF NOT EXISTS ix_snapshot_stockouts
    ON nova.inventory_snapshot (as_of_date, drug_id)
    WHERE qty_unmet > 0;

-- ---------------------------------------------------------------------
-- dispense: demand aggregation feeds every forecasting feature.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_dispense_branch_drug_time
    ON nova.dispense (branch_id, drug_id, dispensed_at DESC);

CREATE INDEX IF NOT EXISTS ix_dispense_time
    ON nova.dispense (dispensed_at);

CREATE INDEX IF NOT EXISTS ix_dispense_line
    ON nova.dispense (prescription_line_id);

-- ---------------------------------------------------------------------
-- prescription: prescriber-centric access drives the P7 anomaly graph;
-- patient-centric access drives the ported prescription_report function.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_prescription_patient_time
    ON nova.prescription (patient_id, prescribed_at DESC);

CREATE INDEX IF NOT EXISTS ix_prescription_prescriber_time
    ON nova.prescription (prescriber_id, prescribed_at DESC);

CREATE INDEX IF NOT EXISTS ix_prescription_branch_time
    ON nova.prescription (branch_id, prescribed_at DESC);

CREATE INDEX IF NOT EXISTS ix_rx_line_drug
    ON nova.prescription_line (drug_id);

-- ---------------------------------------------------------------------
-- Reference lookups
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_drug_company
    ON nova.drug (company_id);

-- Controlled-substance monitoring is a frequent, highly selective filter.
CREATE INDEX IF NOT EXISTS ix_drug_controlled
    ON nova.drug (drug_id)
    WHERE is_controlled;

CREATE INDEX IF NOT EXISTS ix_patient_primary_prescriber
    ON nova.patient (primary_prescriber_id);

CREATE INDEX IF NOT EXISTS ix_branch_region
    ON nova.branch (region);

-- ---------------------------------------------------------------------
-- Lots: FEFO (first-expiry-first-out) picking needs expiry order within a
-- (branch, drug), restricted to lots that still hold stock.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_lot_fefo
    ON nova.inventory_lot (branch_id, drug_id, expires_on)
    WHERE qty_remaining > 0;

-- ---------------------------------------------------------------------
-- Replenishment: policy comparison scans by policy and date.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_replenishment_policy_date
    ON nova.replenishment_order (policy_name, ordered_on);

CREATE INDEX IF NOT EXISTS ix_replenishment_open
    ON nova.replenishment_order (branch_id, drug_id, expected_on)
    WHERE status IN ('placed', 'in_transit');

-- Price lookup as of a date.
CREATE INDEX IF NOT EXISTS ix_price_lookup
    ON nova.branch_drug_price (branch_id, drug_id, effective_from DESC);

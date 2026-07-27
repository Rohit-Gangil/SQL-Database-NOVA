-- =====================================================================
-- NOVA · Layer 0 · Inventory
--
-- THE STRUCTURAL FIX OF PHASE 2.
--
-- The original table (legacy/NOVA_DB.sql:103-108):
--
--     CREATE TABLE Stock (
--         pharmacy_1 VARCHAR2(100) PRIMARY KEY,   -- one row per pharmacy
--         stock      VARCHAR2(100)                -- inventory as a string
--     );
--
-- It cannot answer "how many units of drug D does branch B hold on date T"
-- because it has no drug column, no date column, and no numeric quantity.
-- With one row per pharmacy it cannot even hold two drugs. Every downstream
-- claim in this project -- forecast, reorder quantity, cost saved -- depends
-- on that question being answerable.
--
-- Note also that the original `pharmacy_stock` procedure (legacy:793-818)
-- never reads Stock at all; it reads Pharmacy_Sells, which is a price list.
-- The reported "stock" was the assortment, not the inventory.
--
-- Replaced by three tables:
--   inventory_lot       -- physical stock with expiry dates (perishability)
--   inventory_snapshot  -- daily position per (branch, drug) (the ledger)
--   replenishment_order -- orders placed, and under which policy
-- =====================================================================

-- ---------------------------------------------------------------------
-- Lots. Expiry is tracked per lot because that is how pharmacies work and
-- because "units destroyed on expiry" is one of the three cost terms the
-- flagship optimises. Without lots there is no waste metric.
-- ---------------------------------------------------------------------
CREATE TABLE nova.inventory_lot (
    lot_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id     bigint  NOT NULL REFERENCES nova.branch(branch_id) ON DELETE CASCADE,
    drug_id       bigint  NOT NULL REFERENCES nova.drug(drug_id)     ON DELETE RESTRICT,
    lot_code      text    NOT NULL,
    qty_received  integer NOT NULL,
    qty_remaining integer NOT NULL,
    received_on   date    NOT NULL,
    expires_on    date    NOT NULL,
    unit_cost     numeric(10,2) NOT NULL,

    CONSTRAINT lot_code_uq        UNIQUE (branch_id, drug_id, lot_code),
    CONSTRAINT lot_qty_nonneg     CHECK (qty_received > 0 AND qty_remaining >= 0),
    CONSTRAINT lot_qty_consistent CHECK (qty_remaining <= qty_received),
    CONSTRAINT lot_expiry_after   CHECK (expires_on > received_on)
);

-- ---------------------------------------------------------------------
-- Daily inventory position. One row per (branch, drug, date).
-- This is the table the entire analytics stack reads.
--
-- The flow identity that must hold for every row:
--   qty_open + qty_received = qty_dispensed + qty_expired + qty_adjusted + qty_close
--
-- It is enforced as a CHECK rather than trusted, because a ledger that
-- does not balance produces forecasts that look fine and are wrong.
-- ---------------------------------------------------------------------
CREATE TABLE nova.inventory_snapshot (
    branch_id       bigint  NOT NULL REFERENCES nova.branch(branch_id) ON DELETE CASCADE,
    drug_id         bigint  NOT NULL REFERENCES nova.drug(drug_id)     ON DELETE RESTRICT,
    as_of_date      date    NOT NULL,

    qty_open        integer NOT NULL,
    qty_received    integer NOT NULL DEFAULT 0,
    qty_dispensed   integer NOT NULL DEFAULT 0,
    qty_expired     integer NOT NULL DEFAULT 0,
    qty_adjusted    integer NOT NULL DEFAULT 0,   -- shrinkage, damage, corrections
    qty_close       integer NOT NULL,

    -- Demand that could not be served. Distinct from qty_dispensed: this is
    -- what makes the difference between observed sales and true demand
    -- measurable rather than assumed.
    qty_unmet       integer NOT NULL DEFAULT 0,

    -- Policy state as of this date, stored rather than recomputed, so a
    -- backtest can reconstruct exactly what the incumbent policy would
    -- have done on this day.
    reorder_point   integer,
    order_up_to     integer,
    lead_time_days  smallint NOT NULL DEFAULT 3,
    policy_name     text     NOT NULL DEFAULT 'incumbent_fixed_rop',

    PRIMARY KEY (branch_id, drug_id, as_of_date),

    CONSTRAINT snap_qty_nonneg CHECK (
        qty_open >= 0 AND qty_received >= 0 AND qty_dispensed >= 0
        AND qty_expired >= 0 AND qty_close >= 0 AND qty_unmet >= 0
    ),
    CONSTRAINT snap_flow_balances CHECK (
        qty_open + qty_received - qty_dispensed - qty_expired + qty_adjusted = qty_close
    ),
    -- You cannot have unmet demand while holding stock of that drug at open.
    -- If this fires, the simulator or the ETL is wrong.
    CONSTRAINT snap_unmet_implies_empty CHECK (
        qty_unmet = 0 OR qty_open + qty_received - qty_dispensed = 0
    ),
    CONSTRAINT snap_lead_time_pos CHECK (lead_time_days > 0)
);

COMMENT ON TABLE nova.inventory_snapshot IS
    'Daily inventory ledger per (branch, drug). Replaces the original Stock table, which had neither a drug nor a date column.';

-- Declarative partitioning was considered and rejected for now: at ~5M rows
-- the planner handles this fine with the indexes in db/indexes/, and
-- partitioning would complicate the cold-start experience for a reviewer.
-- Revisit above ~50M rows. (docs/DECISIONS.md D-005)

-- ---------------------------------------------------------------------
-- Replenishment orders. Records which policy produced each order, which is
-- what makes the head-to-head comparison in P6 auditable rather than
-- asserted.
-- ---------------------------------------------------------------------
CREATE TYPE nova.order_status AS ENUM ('placed', 'in_transit', 'received', 'cancelled');

CREATE TABLE nova.replenishment_order (
    order_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id     bigint  NOT NULL REFERENCES nova.branch(branch_id) ON DELETE CASCADE,
    drug_id       bigint  NOT NULL REFERENCES nova.drug(drug_id)     ON DELETE RESTRICT,
    company_id    bigint  REFERENCES nova.company(company_id)        ON DELETE SET NULL,
    ordered_on    date    NOT NULL,
    expected_on   date    NOT NULL,
    received_on   date,
    qty_ordered   integer NOT NULL,
    qty_received  integer,
    unit_cost     numeric(10,2) NOT NULL,
    status        nova.order_status NOT NULL DEFAULT 'placed',
    policy_name   text    NOT NULL,

    CONSTRAINT order_qty_pos      CHECK (qty_ordered > 0),
    CONSTRAINT order_recv_nonneg  CHECK (qty_received IS NULL OR qty_received >= 0),
    CONSTRAINT order_dates_order  CHECK (expected_on >= ordered_on),
    CONSTRAINT order_recv_agrees  CHECK (
        (status = 'received') = (received_on IS NOT NULL AND qty_received IS NOT NULL)
    )
);

COMMENT ON COLUMN nova.replenishment_order.policy_name IS
    'Which policy generated this order (incumbent_fixed_rop | newsvendor_lgbm | ...). Enables auditable head-to-head cost comparison in P6.';

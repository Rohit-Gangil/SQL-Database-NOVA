-- =====================================================================
-- NOVA · Row-level security and grants
--
-- Threat model this addresses: a branch pharmacist authenticated to the
-- application should be able to read their own branch's inventory and
-- prescriptions, and nobody else's. In the original schema every table was
-- world-readable to any connected user, and patient national identifiers
-- were in the clear.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Base grants. Note what nova_analyst and nova_llm do NOT receive:
-- nova.patient and nova.prescriber. They get the de-identified views only.
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA nova TO nova_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA nova TO nova_app;

GRANT SELECT ON
    nova.company, nova.drug, nova.branch, nova.supply_contract,
    nova.branch_drug_price, nova.prescription, nova.prescription_line,
    nova.dispense, nova.inventory_lot, nova.inventory_snapshot,
    nova.replenishment_order,
    nova.v_patient_deid, nova.v_prescriber_deid
TO nova_analyst;

-- The text-to-SQL role (P11). SELECT only, de-identified only.
-- A generated statement cannot write because the role has no privilege to,
-- not because a prompt asked it not to.
GRANT SELECT ON
    nova.company, nova.drug, nova.branch,
    nova.inventory_snapshot, nova.dispense,
    nova.v_patient_deid, nova.v_prescriber_deid
TO nova_llm;

ALTER ROLE nova_llm SET statement_timeout = '10s';
ALTER ROLE nova_llm SET default_transaction_read_only = on;

-- Neither analytical role may ever reach the raw identifiers or the salt.
REVOKE ALL ON nova.patient, nova.prescriber FROM nova_analyst, nova_llm;
REVOKE ALL ON SCHEMA nova_admin FROM nova_analyst, nova_llm, nova_app;
REVOKE ALL ON SCHEMA nova_truth FROM nova_analyst, nova_llm, nova_app;

-- ---------------------------------------------------------------------
-- Branch-scoped row-level security.
--
-- The application sets `nova.branch_id` per session/transaction; the policy
-- reads it. A missing setting yields no rows rather than all rows -- fail
-- closed, because the failure mode of fail-open is a cross-branch data leak.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nova.current_branch_id()
RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('nova.branch_id', true), '')::bigint;
$$;

ALTER TABLE nova.inventory_snapshot  ENABLE ROW LEVEL SECURITY;
ALTER TABLE nova.inventory_lot       ENABLE ROW LEVEL SECURITY;
ALTER TABLE nova.prescription        ENABLE ROW LEVEL SECURITY;
ALTER TABLE nova.dispense            ENABLE ROW LEVEL SECURITY;
ALTER TABLE nova.replenishment_order ENABLE ROW LEVEL SECURITY;

CREATE POLICY branch_isolation_snapshot ON nova.inventory_snapshot
    FOR ALL TO nova_app
    USING (branch_id = nova.current_branch_id());

CREATE POLICY branch_isolation_lot ON nova.inventory_lot
    FOR ALL TO nova_app
    USING (branch_id = nova.current_branch_id());

CREATE POLICY branch_isolation_prescription ON nova.prescription
    FOR ALL TO nova_app
    USING (branch_id = nova.current_branch_id());

CREATE POLICY branch_isolation_dispense ON nova.dispense
    FOR ALL TO nova_app
    USING (branch_id = nova.current_branch_id());

CREATE POLICY branch_isolation_replenishment ON nova.replenishment_order
    FOR ALL TO nova_app
    USING (branch_id = nova.current_branch_id());

-- The analytics pipeline legitimately reads across all branches -- a
-- chain-wide forecast is the entire point -- so it is granted a bypass
-- explicitly and visibly, rather than by weakening the policies above.
CREATE POLICY analyst_reads_all_snapshot ON nova.inventory_snapshot
    FOR SELECT TO nova_analyst USING (true);
CREATE POLICY analyst_reads_all_dispense ON nova.dispense
    FOR SELECT TO nova_analyst USING (true);
CREATE POLICY analyst_reads_all_lot ON nova.inventory_lot
    FOR SELECT TO nova_analyst USING (true);
CREATE POLICY analyst_reads_all_prescription ON nova.prescription
    FOR SELECT TO nova_analyst USING (true);
CREATE POLICY analyst_reads_all_replenishment ON nova.replenishment_order
    FOR SELECT TO nova_analyst USING (true);

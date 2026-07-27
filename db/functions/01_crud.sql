-- =====================================================================
-- NOVA · Layer 0 · Write API (PL/pgSQL port of the Oracle procedures)
--
-- Three systematic changes from legacy/NOVA_DB.sql, applied to all 24:
--
-- 1. NO `COMMIT` INSIDE. Every original procedure committed (e.g. legacy:172)
--    and rolled back on error. A callee that owns the transaction cannot be
--    composed -- you can never wrap "add prescription + add lines" in one
--    atomic unit, which is exactly what the application needs.
--
-- 2. ERRORS RAISE. Every original procedure ended in
--        EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE('Error: ' || SQLERRM)
--    which prints to a console buffer the caller usually is not reading, and
--    then returns *successfully*. A failed insert was indistinguishable from
--    a successful one. Here failures raise SQLSTATE-coded exceptions.
--
-- 3. VALIDATION MOVED TO THE SCHEMA. Most original procedures opened with a
--    `SELECT COUNT(*) INTO v_exists` existence check (e.g. legacy:187, :706).
--    That is a foreign key, enforced declaratively, without a race between
--    the check and the write. Functions here carry only the rules a
--    constraint cannot express.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Companies / branches / drugs
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nova.add_company(p_name text, p_phone text DEFAULT NULL,
                                            p_country text DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v_id bigint;
BEGIN
    INSERT INTO nova.company (name, phone, country)
    VALUES (p_name, p_phone, p_country)
    RETURNING company_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'Company % already exists', p_name
            USING ERRCODE = 'unique_violation';
END $$;

CREATE OR REPLACE FUNCTION nova.add_branch(p_code text, p_name text, p_city text,
                                           p_region text, p_address text DEFAULT NULL,
                                           p_phone text DEFAULT NULL,
                                           p_opened_on date DEFAULT CURRENT_DATE)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v_id bigint;
BEGIN
    INSERT INTO nova.branch (code, name, city, region, address, phone, opened_on)
    VALUES (p_code, p_name, p_city, p_region, p_address, p_phone, p_opened_on)
    RETURNING branch_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'Branch code % already exists', p_code
            USING ERRCODE = 'unique_violation';
END $$;

CREATE OR REPLACE FUNCTION nova.add_drug(p_trade_name text, p_company text,
                                         p_formula text, p_unit_cost numeric,
                                         p_sale_price numeric,
                                         p_shelf_life_days int DEFAULT 730,
                                         p_criticality smallint DEFAULT 3)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_company_id bigint;
    v_id         bigint;
BEGIN
    SELECT company_id INTO v_company_id FROM nova.company WHERE name = p_company;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown manufacturer: %', p_company
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    INSERT INTO nova.drug (trade_name, company_id, formula, unit_cost, sale_price,
                           shelf_life_days, criticality)
    VALUES (p_trade_name, v_company_id, p_formula, p_unit_cost, p_sale_price,
            p_shelf_life_days, p_criticality)
    RETURNING drug_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'Drug % by % already exists', p_trade_name, p_company
            USING ERRCODE = 'unique_violation';
END $$;

-- ---------------------------------------------------------------------
-- People. The raw national identifier is accepted as an argument and
-- hashed immediately; it is never stored and never returned.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nova.add_prescriber(p_national_id text, p_name text,
                                               p_specialty text DEFAULT NULL,
                                               p_years_experience smallint DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v_id bigint;
BEGIN
    IF p_national_id !~ '^\d{12}$' THEN
        RAISE EXCEPTION 'National identifier must be 12 digits'
            USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO nova.prescriber (national_id_hash, national_id_last4, display_name,
                                 specialty, years_experience)
    VALUES (nova.hash_national_id(p_national_id), right(p_national_id, 4),
            p_name, p_specialty, p_years_experience)
    RETURNING prescriber_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'Prescriber already registered'
            USING ERRCODE = 'unique_violation';
END $$;

CREATE OR REPLACE FUNCTION nova.add_patient(p_national_id text, p_name text,
                                            p_birth_year smallint DEFAULT NULL,
                                            p_sex char DEFAULT NULL,
                                            p_city text DEFAULT NULL,
                                            p_region text DEFAULT NULL,
                                            p_primary_prescriber bigint DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v_id bigint;
BEGIN
    IF p_national_id !~ '^\d{12}$' THEN
        RAISE EXCEPTION 'National identifier must be 12 digits'
            USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO nova.patient (national_id_hash, national_id_last4, display_name,
                              birth_year, sex, city, region, primary_prescriber_id)
    VALUES (nova.hash_national_id(p_national_id), right(p_national_id, 4),
            p_name, p_birth_year, p_sex, p_city, p_region, p_primary_prescriber)
    RETURNING patient_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'Patient already registered'
            USING ERRCODE = 'unique_violation';
END $$;

-- ---------------------------------------------------------------------
-- Prescriptions. The original could not record two prescriptions from the
-- same doctor to the same patient on the same day (composite PK,
-- legacy:124). This can.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nova.add_prescription(p_prescriber_id bigint,
                                                 p_patient_id bigint,
                                                 p_branch_id bigint,
                                                 p_prescribed_at timestamptz DEFAULT now(),
                                                 p_diagnosis_code text DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v_id bigint;
BEGIN
    INSERT INTO nova.prescription (prescriber_id, patient_id, branch_id,
                                   prescribed_at, diagnosis_code)
    VALUES (p_prescriber_id, p_patient_id, p_branch_id, p_prescribed_at, p_diagnosis_code)
    RETURNING prescription_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN foreign_key_violation THEN
        RAISE EXCEPTION 'Unknown prescriber, patient or branch'
            USING ERRCODE = 'foreign_key_violation';
END $$;

CREATE OR REPLACE FUNCTION nova.add_prescription_line(p_prescription_id bigint,
                                                      p_drug_id bigint,
                                                      p_qty int,
                                                      p_days_supply smallint DEFAULT NULL,
                                                      p_refills smallint DEFAULT 0)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_id          bigint;
    v_controlled  boolean;
BEGIN
    SELECT is_controlled INTO v_controlled FROM nova.drug WHERE drug_id = p_drug_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown drug id %', p_drug_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    -- A rule a CHECK constraint cannot express, because it spans two tables:
    -- controlled substances may not carry authorised refills.
    IF v_controlled AND p_refills > 0 THEN
        RAISE EXCEPTION 'Controlled substances cannot be prescribed with refills'
            USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO nova.prescription_line (prescription_id, drug_id, qty_prescribed,
                                        days_supply, refills_authorised)
    VALUES (p_prescription_id, p_drug_id, p_qty, p_days_supply, p_refills)
    RETURNING prescription_line_id INTO v_id;
    RETURN v_id;
END $$;

-- ---------------------------------------------------------------------
-- Dispensing with FEFO (first-expiry-first-out) lot depletion.
--
-- No equivalent existed in the original schema. This is the function that
-- generates the demand signal: it decrements real lots, records what could
-- not be served, and is therefore the origin of both the stockout metric
-- and the censored-demand problem handled in P5.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nova.dispense_drug(p_prescription_line_id bigint,
                                              p_branch_id bigint,
                                              p_qty int,
                                              p_dispensed_at timestamptz DEFAULT now())
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_drug_id    bigint;
    v_remaining  int := p_qty;
    v_take       int;
    v_price      numeric(10,2);
    v_dispense_id bigint;
    v_lot        record;
BEGIN
    IF p_qty <= 0 THEN
        RAISE EXCEPTION 'Dispense quantity must be positive'
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT drug_id INTO v_drug_id
    FROM nova.prescription_line WHERE prescription_line_id = p_prescription_line_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown prescription line %', p_prescription_line_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    SELECT price INTO v_price
    FROM nova.branch_drug_price
    WHERE branch_id = p_branch_id AND drug_id = v_drug_id
      AND effective_from <= p_dispensed_at::date
      AND (effective_to IS NULL OR effective_to > p_dispensed_at::date)
    ORDER BY effective_from DESC LIMIT 1;

    IF v_price IS NULL THEN
        SELECT sale_price INTO v_price FROM nova.drug WHERE drug_id = v_drug_id;
    END IF;

    -- Deplete lots in expiry order, skipping already-expired stock.
    -- FOR UPDATE because two concurrent dispenses must not both claim the
    -- same units.
    FOR v_lot IN
        SELECT lot_id, qty_remaining
        FROM nova.inventory_lot
        WHERE branch_id = p_branch_id AND drug_id = v_drug_id
          AND qty_remaining > 0
          AND expires_on > p_dispensed_at::date
        ORDER BY expires_on ASC
        FOR UPDATE
    LOOP
        EXIT WHEN v_remaining <= 0;
        v_take := least(v_remaining, v_lot.qty_remaining);
        UPDATE nova.inventory_lot
           SET qty_remaining = qty_remaining - v_take
         WHERE lot_id = v_lot.lot_id;
        v_remaining := v_remaining - v_take;
    END LOOP;

    INSERT INTO nova.dispense (prescription_line_id, branch_id, drug_id, dispensed_at,
                               qty_dispensed, qty_unmet, unmet_reason, unit_price)
    VALUES (p_prescription_line_id, p_branch_id, v_drug_id, p_dispensed_at,
            p_qty - v_remaining, v_remaining,
            CASE WHEN v_remaining > 0 THEN 'out_of_stock'::nova.unmet_reason
                 ELSE 'none'::nova.unmet_reason END,
            v_price)
    RETURNING dispense_id INTO v_dispense_id;

    RETURN v_dispense_id;
END $$;

COMMENT ON FUNCTION nova.dispense_drug IS
    'FEFO lot depletion. Records unmet units rather than failing, so stockouts become measurable data instead of lost transactions.';

-- ---------------------------------------------------------------------
-- Expiry sweep. Moves expired units out of stock and reports the loss.
-- The waste term of the P6 cost function comes from here.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nova.expire_lots(p_as_of date DEFAULT CURRENT_DATE)
RETURNS TABLE (branch_id bigint, drug_id bigint, units_expired bigint, cost_written_off numeric)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    -- The pre-update quantity must be captured in a separate CTE: an
    -- UPDATE ... RETURNING in PostgreSQL returns the NEW row values, so
    -- `RETURNING qty_remaining` after `SET qty_remaining = 0` would report
    -- zero units written off on every sweep -- a silently empty waste metric.
    WITH to_expire AS (
        SELECT l.lot_id, l.branch_id, l.drug_id,
               l.qty_remaining AS units, l.unit_cost
        FROM nova.inventory_lot l
        WHERE l.expires_on <= p_as_of AND l.qty_remaining > 0
        FOR UPDATE
    ),
    zeroed AS (
        UPDATE nova.inventory_lot l
           SET qty_remaining = 0
          FROM to_expire t
         WHERE l.lot_id = t.lot_id
        RETURNING t.branch_id AS b_id, t.drug_id AS d_id, t.units, t.unit_cost
    )
    SELECT z.b_id, z.d_id,
           sum(z.units)::bigint,
           sum(z.units * z.unit_cost)::numeric
    FROM zeroed z
    GROUP BY z.b_id, z.d_id;
END $$;

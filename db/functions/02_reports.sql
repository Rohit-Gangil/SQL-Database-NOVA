-- =====================================================================
-- NOVA · Layer 0 · Read API (port of the six Oracle report procedures)
--
-- The originals printed to DBMS_OUTPUT (legacy:701-878): a console buffer.
-- Nothing could consume them -- not an application, not a BI tool, not a
-- test. They were demo scripts wearing the costume of an API.
--
-- Here every report is a set-returning function. The same information is
-- now joinable, testable, and callable from Python.
-- =====================================================================

-- Was: prescription_report (legacy:701)
CREATE OR REPLACE FUNCTION nova.prescription_report(p_patient_id bigint,
                                                    p_from date,
                                                    p_to date)
RETURNS TABLE (
    prescription_id bigint,
    prescribed_at   timestamptz,
    prescriber_id   bigint,
    prescriber_name text,
    specialty       text,
    branch_name     text,
    drug_count      bigint,
    total_qty       bigint
)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF p_from > p_to THEN
        RAISE EXCEPTION 'Start date % is after end date %', p_from, p_to
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    -- The original returned silently when the patient did not exist
    -- (legacy:708-711), so "no such patient" and "patient with no
    -- prescriptions" were indistinguishable to the caller.
    IF NOT EXISTS (SELECT 1 FROM nova.patient WHERE patient_id = p_patient_id) THEN
        RAISE EXCEPTION 'Unknown patient id %', p_patient_id
            USING ERRCODE = 'no_data_found';
    END IF;

    RETURN QUERY
    SELECT rx.prescription_id,
           rx.prescribed_at,
           pr.prescriber_id,
           pr.display_name,
           pr.specialty,
           b.name,
           count(rl.prescription_line_id),
           coalesce(sum(rl.qty_prescribed), 0)::bigint
    FROM nova.prescription rx
    JOIN nova.prescriber pr        ON pr.prescriber_id = rx.prescriber_id
    JOIN nova.branch b             ON b.branch_id = rx.branch_id
    LEFT JOIN nova.prescription_line rl ON rl.prescription_id = rx.prescription_id
    WHERE rx.patient_id = p_patient_id
      AND rx.prescribed_at >= p_from
      AND rx.prescribed_at < (p_to + 1)      -- half-open: BETWEEN on a
                                             -- timestamp silently drops
                                             -- everything after 00:00 on p_to
    GROUP BY rx.prescription_id, rx.prescribed_at, pr.prescriber_id,
             pr.display_name, pr.specialty, b.name
    ORDER BY rx.prescribed_at;
END $$;

COMMENT ON FUNCTION nova.prescription_report IS
    'Half-open date range [p_from, p_to+1). The original used BETWEEN against a DATE column, which excluded same-day afternoon prescriptions once timestamps were introduced.';

-- Was: prescription_details (legacy:734)
CREATE OR REPLACE FUNCTION nova.prescription_details(p_prescription_id bigint)
RETURNS TABLE (
    drug_id       bigint,
    trade_name    text,
    company_name  text,
    qty_prescribed integer,
    qty_dispensed bigint,
    qty_unmet     bigint,
    days_supply   smallint
)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM nova.prescription WHERE prescription_id = p_prescription_id) THEN
        RAISE EXCEPTION 'Unknown prescription id %', p_prescription_id
            USING ERRCODE = 'no_data_found';
    END IF;

    RETURN QUERY
    SELECT d.drug_id, d.trade_name, c.name,
           rl.qty_prescribed,
           coalesce(sum(dp.qty_dispensed), 0)::bigint,
           coalesce(sum(dp.qty_unmet), 0)::bigint,
           rl.days_supply
    FROM nova.prescription_line rl
    JOIN nova.drug d    ON d.drug_id = rl.drug_id
    JOIN nova.company c ON c.company_id = d.company_id
    LEFT JOIN nova.dispense dp ON dp.prescription_line_id = rl.prescription_line_id
    WHERE rl.prescription_id = p_prescription_id
    GROUP BY d.drug_id, d.trade_name, c.name, rl.qty_prescribed, rl.days_supply
    ORDER BY d.trade_name;
END $$;

-- Was: drugs_by_company (legacy:768)
CREATE OR REPLACE FUNCTION nova.drugs_by_company(p_company text)
RETURNS TABLE (
    drug_id     bigint,
    trade_name  text,
    formula     text,
    dosage_form text,
    unit_cost   numeric,
    sale_price  numeric,
    is_controlled boolean
)
LANGUAGE plpgsql STABLE AS $$
DECLARE v_company_id bigint;
BEGIN
    SELECT company_id INTO v_company_id FROM nova.company WHERE name = p_company;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown manufacturer: %', p_company
            USING ERRCODE = 'no_data_found';
    END IF;

    RETURN QUERY
    SELECT d.drug_id, d.trade_name, d.formula, d.dosage_form,
           d.unit_cost, d.sale_price, d.is_controlled
    FROM nova.drug d
    WHERE d.company_id = v_company_id
    ORDER BY d.trade_name;
END $$;

-- Was: pharmacy_stock (legacy:793).
-- The original queried Pharmacy_Sells -- the PRICE LIST -- and reported it
-- as stock. It never touched the Stock table. This one reads the actual
-- inventory position, including days-of-cover and expiry exposure.
CREATE OR REPLACE FUNCTION nova.branch_stock(p_branch_id bigint,
                                             p_as_of date DEFAULT CURRENT_DATE)
RETURNS TABLE (
    drug_id         bigint,
    trade_name      text,
    qty_on_hand     integer,
    reorder_point   integer,
    below_reorder   boolean,
    days_of_cover   numeric,
    units_expiring_30d bigint
)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM nova.branch WHERE branch_id = p_branch_id) THEN
        RAISE EXCEPTION 'Unknown branch id %', p_branch_id
            USING ERRCODE = 'no_data_found';
    END IF;

    RETURN QUERY
    WITH latest AS (
        SELECT DISTINCT ON (s.drug_id)
               s.drug_id, s.qty_close, s.reorder_point
        FROM nova.inventory_snapshot s
        WHERE s.branch_id = p_branch_id AND s.as_of_date <= p_as_of
        ORDER BY s.drug_id, s.as_of_date DESC
    ),
    recent_demand AS (
        SELECT s.drug_id, avg(s.qty_dispensed)::numeric AS avg_daily
        FROM nova.inventory_snapshot s
        WHERE s.branch_id = p_branch_id
          AND s.as_of_date > p_as_of - 28
          AND s.as_of_date <= p_as_of
        GROUP BY s.drug_id
    ),
    expiring AS (
        SELECT l.drug_id, sum(l.qty_remaining)::bigint AS units
        FROM nova.inventory_lot l
        WHERE l.branch_id = p_branch_id
          AND l.qty_remaining > 0
          AND l.expires_on BETWEEN p_as_of AND p_as_of + 30
        GROUP BY l.drug_id
    )
    SELECT lt.drug_id, d.trade_name, lt.qty_close, lt.reorder_point,
           (lt.reorder_point IS NOT NULL AND lt.qty_close < lt.reorder_point),
           CASE WHEN coalesce(rd.avg_daily, 0) > 0
                THEN round(lt.qty_close / rd.avg_daily, 1)
                ELSE NULL END,
           coalesce(ex.units, 0)
    FROM latest lt
    JOIN nova.drug d ON d.drug_id = lt.drug_id
    LEFT JOIN recent_demand rd ON rd.drug_id = lt.drug_id
    LEFT JOIN expiring ex      ON ex.drug_id = lt.drug_id
    ORDER BY d.trade_name;
END $$;

-- Was: contact_details (legacy:820) -- name kept as contract_details, since
-- the original name was a typo for "contract".
CREATE OR REPLACE FUNCTION nova.contract_details(p_branch_id bigint, p_company_id bigint)
RETURNS TABLE (
    contract_id bigint,
    branch_name text,
    company_name text,
    starts_on   date,
    ends_on     date,
    is_active   boolean,
    supervisor  text,
    terms       text
)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY
    SELECT sc.contract_id, b.name, c.name,
           lower(sc.valid_period), upper(sc.valid_period),
           sc.valid_period @> CURRENT_DATE,
           sc.supervisor, sc.terms
    FROM nova.supply_contract sc
    JOIN nova.branch b  ON b.branch_id = sc.branch_id
    JOIN nova.company c ON c.company_id = sc.company_id
    WHERE sc.branch_id = p_branch_id AND sc.company_id = p_company_id
    ORDER BY lower(sc.valid_period) DESC;
END $$;

-- Was: patients_of_doctor (legacy:852). Returns de-identified rows: a
-- prescriber-level report has no business exposing patient names.
CREATE OR REPLACE FUNCTION nova.patients_of_prescriber(p_prescriber_id bigint)
RETURNS TABLE (
    patient_id      bigint,
    age_bucket      integer,
    sex             char(1),
    region          text,
    prescription_count bigint,
    last_seen       timestamptz
)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM nova.prescriber WHERE prescriber_id = p_prescriber_id) THEN
        RAISE EXCEPTION 'Unknown prescriber id %', p_prescriber_id
            USING ERRCODE = 'no_data_found';
    END IF;

    RETURN QUERY
    SELECT v.patient_id, v.age_bucket, v.sex, v.region,
           count(rx.prescription_id), max(rx.prescribed_at)
    FROM nova.v_patient_deid v
    LEFT JOIN nova.prescription rx
           ON rx.patient_id = v.patient_id
          AND rx.prescriber_id = p_prescriber_id
    WHERE v.primary_prescriber_id = p_prescriber_id
       OR rx.prescription_id IS NOT NULL
    GROUP BY v.patient_id, v.age_bucket, v.sex, v.region
    ORDER BY max(rx.prescribed_at) DESC NULLS LAST;
END $$;

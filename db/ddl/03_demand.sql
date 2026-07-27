-- =====================================================================
-- NOVA · Layer 0 · Demand: prescriptions and dispensing
--
-- Original: Prescription keyed (doctor_id, patient_id, date_prescribed)
-- (legacy:120-127) and Drugs_Prescribed repeating all four of those
-- columns plus the drug (legacy:129-141).
--
-- Two defects that mattered:
--   1. A patient could not receive two prescriptions from the same doctor
--      on the same day -- the PK forbade it. Real clinics do this daily.
--   2. Drugs_Prescribed carried a 5-column composite FK, so every join
--      from a prescribed drug back to its prescription dragged the
--      patient's national ID through the query plan.
-- =====================================================================

CREATE TABLE nova.prescription (
    prescription_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prescriber_id   bigint      NOT NULL REFERENCES nova.prescriber(prescriber_id) ON DELETE RESTRICT,
    patient_id      bigint      NOT NULL REFERENCES nova.patient(patient_id)       ON DELETE RESTRICT,
    branch_id       bigint      NOT NULL REFERENCES nova.branch(branch_id)         ON DELETE RESTRICT,
    prescribed_at   timestamptz NOT NULL,
    diagnosis_code  text,                              -- ICD-10-ish, optional
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT prescription_not_future CHECK (prescribed_at <= now() + interval '1 day')
);

CREATE TABLE nova.prescription_line (
    prescription_line_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prescription_id      bigint   NOT NULL REFERENCES nova.prescription(prescription_id) ON DELETE CASCADE,
    drug_id              bigint   NOT NULL REFERENCES nova.drug(drug_id) ON DELETE RESTRICT,
    qty_prescribed       integer  NOT NULL,
    days_supply          smallint,
    refills_authorised   smallint NOT NULL DEFAULT 0,

    CONSTRAINT rx_line_uq        UNIQUE (prescription_id, drug_id),
    CONSTRAINT rx_line_qty_pos   CHECK (qty_prescribed > 0),
    CONSTRAINT rx_line_days_pos  CHECK (days_supply IS NULL OR days_supply > 0),
    CONSTRAINT rx_line_refills   CHECK (refills_authorised >= 0)
);

-- ---------------------------------------------------------------------
-- Dispense events.
--
-- This table did not exist in the original schema, and its absence is the
-- reason the original data could not support forecasting at all. A
-- prescription is *intent*; a dispense is *demand realised*. The gap
-- between them is the signal:
--
--   qty_prescribed - qty_dispensed > 0  and unmet_reason = 'out_of_stock'
--       => censored demand. The branch wanted to sell and could not.
--
-- Censoring is the subtle part of retail demand forecasting: naively
-- training on dispensed units teaches the model that a stockout day had
-- low demand, which drives the next forecast down, which causes the next
-- stockout. P5 handles the correction; the schema has to record the fact
-- in the first place.
-- ---------------------------------------------------------------------
CREATE TYPE nova.unmet_reason AS ENUM (
    'none', 'out_of_stock', 'patient_declined', 'substituted', 'expired_stock'
);

CREATE TABLE nova.dispense (
    dispense_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prescription_line_id bigint  NOT NULL REFERENCES nova.prescription_line(prescription_line_id) ON DELETE CASCADE,
    branch_id            bigint  NOT NULL REFERENCES nova.branch(branch_id) ON DELETE RESTRICT,
    drug_id              bigint  NOT NULL REFERENCES nova.drug(drug_id)     ON DELETE RESTRICT,
    dispensed_at         timestamptz NOT NULL,
    qty_dispensed        integer NOT NULL,
    qty_unmet            integer NOT NULL DEFAULT 0,
    unmet_reason         nova.unmet_reason NOT NULL DEFAULT 'none',
    substituted_drug_id  bigint  REFERENCES nova.drug(drug_id) ON DELETE SET NULL,
    unit_price           numeric(10,2) NOT NULL,

    CONSTRAINT dispense_qty_nonneg   CHECK (qty_dispensed >= 0 AND qty_unmet >= 0),
    CONSTRAINT dispense_qty_positive CHECK (qty_dispensed + qty_unmet > 0),
    -- Unmet units require a reason, and a reason requires unmet units.
    CONSTRAINT dispense_reason_agrees CHECK (
        (qty_unmet = 0 AND unmet_reason = 'none') OR
        (qty_unmet > 0 AND unmet_reason <> 'none')
    ),
    CONSTRAINT dispense_substitution_agrees CHECK (
        (unmet_reason = 'substituted') = (substituted_drug_id IS NOT NULL)
    )
);

COMMENT ON COLUMN nova.dispense.qty_unmet IS
    'Units the patient wanted that the branch could not supply. The stockout signal, and the source of demand censoring corrected in P5.';

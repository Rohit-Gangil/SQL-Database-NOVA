-- =====================================================================
-- NOVA · Layer 0 · People (prescribers, patients)
--
-- This file carries the PII redesign. See docs/PII-POLICY.md.
-- Original: Aadhaar stored in plaintext as the PRIMARY KEY of both
-- Doctor (legacy:96) and Patient (legacy:112).
-- =====================================================================

CREATE TABLE nova.prescriber (
    prescriber_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    national_id_hash  bytea       NOT NULL,   -- salted SHA-256, never the raw value
    national_id_last4 char(4),                -- support-desk disambiguation only
    display_name      text        NOT NULL,
    specialty         text,
    years_experience  smallint,
    registered_on     date        NOT NULL DEFAULT CURRENT_DATE,
    created_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT prescriber_nid_uq  UNIQUE (national_id_hash),
    CONSTRAINT prescriber_exp_rng CHECK (years_experience IS NULL
                                         OR years_experience BETWEEN 0 AND 70)
);

CREATE TABLE nova.patient (
    patient_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    national_id_hash      bytea       NOT NULL,
    national_id_last4     char(4),
    display_name          text        NOT NULL,
    -- Birth year, not date of birth, and not a mutable `age` column.
    -- The original stored `age NUMBER` (legacy:115), which is wrong the day
    -- after it is written and cannot be corrected without knowing when it
    -- was recorded. Year of birth is both less identifying and time-stable.
    birth_year            smallint,
    sex                   char(1),
    city                  text,
    region                text,
    home_branch_id        bigint REFERENCES nova.branch(branch_id) ON DELETE SET NULL,
    primary_prescriber_id bigint REFERENCES nova.prescriber(prescriber_id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT patient_nid_uq   UNIQUE (national_id_hash),
    CONSTRAINT patient_year_rng CHECK (birth_year IS NULL
                                       OR birth_year BETWEEN 1900 AND EXTRACT(YEAR FROM CURRENT_DATE)),
    CONSTRAINT patient_sex_vals CHECK (sex IS NULL OR sex IN ('M','F','O'))
);

-- ---------------------------------------------------------------------
-- De-identified views.
--
-- nova_analyst and nova_llm are granted these and NOT the base tables, so
-- an analytical query cannot reach a name or an identifier hash even by
-- accident. Age is bucketed: exact age plus city plus a prescription date
-- is close to re-identifying.
-- ---------------------------------------------------------------------
CREATE VIEW nova.v_patient_deid AS
SELECT
    patient_id,
    CASE
        WHEN birth_year IS NULL THEN NULL
        ELSE width_bucket(EXTRACT(YEAR FROM CURRENT_DATE)::int - birth_year,
                          0, 100, 10)
    END                                   AS age_bucket,
    sex,
    region,
    home_branch_id,
    primary_prescriber_id
FROM nova.patient;

COMMENT ON VIEW nova.v_patient_deid IS
    'De-identified patient projection: no name, no identifier hash, age bucketed to decades. Granted to analyst/LLM roles in place of nova.patient.';

CREATE VIEW nova.v_prescriber_deid AS
SELECT
    prescriber_id,
    specialty,
    years_experience
FROM nova.prescriber;

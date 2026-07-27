-- =====================================================================
-- NOVA · Ground truth (simulator labels)
--
-- Deliberately in a SEPARATE SCHEMA that no application, feature-store or
-- model-training role is granted. The point of a simulator is that we know
-- the answers; the risk of a simulator is that the answers leak into the
-- features and every metric becomes theatre.
--
-- Physical separation beats discipline. A feature query that touches
-- nova_truth fails with a permission error rather than silently producing
-- a 0.99 AUC that means nothing.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS nova_truth;
REVOKE ALL ON SCHEMA nova_truth FROM PUBLIC;

-- Only the evaluation role may read labels.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nova_eval') THEN
        CREATE ROLE nova_eval NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA nova_truth TO nova_eval;

-- ---------------------------------------------------------------------
-- Prescribers the simulator generated as anomalous, and how.
-- Consumed only by P7 evaluation, never by P7 training.
-- ---------------------------------------------------------------------
CREATE TABLE nova_truth.anomalous_prescriber (
    prescriber_id   bigint  PRIMARY KEY,
    anomaly_type    text    NOT NULL,   -- overprescribing | phantom_patients | controlled_ring
    severity        numeric(4,3) NOT NULL,
    active_from     date    NOT NULL,
    active_to       date,
    notes           text,

    CONSTRAINT truth_sev_rng CHECK (severity > 0 AND severity <= 1)
);

-- ---------------------------------------------------------------------
-- Injected supply shocks. Used to explain forecast error honestly: a model
-- is not "wrong" for failing to predict a manufacturer going offline, and
-- error decomposition should say so.
-- ---------------------------------------------------------------------
CREATE TABLE nova_truth.supply_shock (
    shock_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   bigint NOT NULL,
    drug_id      bigint,
    starts_on    date   NOT NULL,
    ends_on      date   NOT NULL,
    severity     numeric(4,3) NOT NULL,   -- fraction of supply withheld
    CONSTRAINT shock_dates  CHECK (ends_on >= starts_on),
    CONSTRAINT shock_sev_rng CHECK (severity > 0 AND severity <= 1)
);

-- ---------------------------------------------------------------------
-- Demand regime changes, for P10 drift detection to have a known answer.
-- ---------------------------------------------------------------------
CREATE TABLE nova_truth.regime_change (
    regime_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    drug_id      bigint,
    branch_id    bigint,
    change_on    date   NOT NULL,
    multiplier   numeric(6,3) NOT NULL,
    description  text,
    CONSTRAINT regime_mult_pos CHECK (multiplier > 0)
);

-- ---------------------------------------------------------------------
-- The true causal effect of the simulated adherence intervention.
--
-- This is what a real dataset can never give you: P8 estimators are scored
-- on whether their confidence interval covers the effect that was actually
-- injected, rather than on whether the output looks plausible.
-- ---------------------------------------------------------------------
CREATE TABLE nova_truth.intervention_effect (
    cohort           text    PRIMARY KEY,
    true_ate         numeric(6,4) NOT NULL,
    true_cate_slope  numeric(6,4),
    description      text
);

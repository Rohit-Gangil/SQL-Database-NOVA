-- =====================================================================
-- NOVA · Layer 0 · Reference entities: companies, drugs, branches
-- =====================================================================

-- ---------------------------------------------------------------------
-- Manufacturer
-- Was: Pharmaceutical_Company, PK on the company name (legacy:82-85).
-- A company can rename; a natural-key PK makes that a cascade.
-- ---------------------------------------------------------------------
CREATE TABLE nova.company (
    company_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text        NOT NULL,
    phone        text,
    country      text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT company_name_uq  UNIQUE (name),
    CONSTRAINT company_name_len CHECK (char_length(name) BETWEEN 1 AND 120)
);

-- ---------------------------------------------------------------------
-- Drug (SKU)
-- Was: Drugs(trade_name, P_name, formula) (legacy:87-93).
--
-- Columns added because the replenishment decision is impossible without
-- them: unit_cost and sale_price give the newsvendor its cost ratio;
-- shelf_life_days makes perishability representable; criticality scales
-- the stockout penalty (running out of an anticoagulant is not the same
-- error as running out of a vitamin); pack_size is the order granularity.
-- ---------------------------------------------------------------------
CREATE TABLE nova.drug (
    drug_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_name         text        NOT NULL,
    company_id         bigint      NOT NULL REFERENCES nova.company(company_id) ON DELETE RESTRICT,
    formula            text,
    atc_code           text,           -- WHO Anatomical Therapeutic Chemical
    rxnorm_cui         text,           -- public vocabulary anchor
    dosage_form        text,           -- tablet | capsule | syrup | injection
    strength           text,
    pack_size          integer     NOT NULL DEFAULT 1,
    unit_cost          numeric(10,2) NOT NULL,
    sale_price         numeric(10,2) NOT NULL,
    shelf_life_days    integer     NOT NULL DEFAULT 730,
    is_controlled      boolean     NOT NULL DEFAULT false,
    requires_cold_chain boolean    NOT NULL DEFAULT false,
    criticality        smallint    NOT NULL DEFAULT 3,
    launched_on        date,
    discontinued_on    date,
    created_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT drug_trade_company_uq UNIQUE (trade_name, company_id),
    CONSTRAINT drug_costs_positive   CHECK (unit_cost > 0 AND sale_price > 0),
    -- A drug sold below cost is a data error, not a business strategy.
    CONSTRAINT drug_margin_sane      CHECK (sale_price >= unit_cost),
    CONSTRAINT drug_pack_positive    CHECK (pack_size >= 1),
    CONSTRAINT drug_shelf_positive   CHECK (shelf_life_days > 0),
    CONSTRAINT drug_criticality_rng  CHECK (criticality BETWEEN 1 AND 5),
    CONSTRAINT drug_lifecycle_order  CHECK (discontinued_on IS NULL
                                            OR launched_on IS NULL
                                            OR discontinued_on >= launched_on)
);

COMMENT ON COLUMN nova.drug.criticality IS
    '1=substitutable convenience item .. 5=life-critical. Scales the stockout penalty in the newsvendor policy (P6).';

-- ---------------------------------------------------------------------
-- Branch
-- Was: Pharmacy, PK on name (legacy:76-80). region added because the
-- forecasting hierarchy is SKU -> branch -> region -> national and the
-- original schema had no level between branch and chain.
-- ---------------------------------------------------------------------
CREATE TABLE nova.branch (
    branch_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code           text        NOT NULL,
    name           text        NOT NULL,
    address        text,
    city           text        NOT NULL,
    region         text        NOT NULL,
    phone          text,
    opened_on      date        NOT NULL,
    closed_on      date,
    floor_area_sqm numeric(8,1),
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT branch_code_uq       UNIQUE (code),
    CONSTRAINT branch_lifecycle_ord CHECK (closed_on IS NULL OR closed_on > opened_on)
);

-- ---------------------------------------------------------------------
-- Supply contract
-- Was: Contract_With (legacy:143-153). The original had no check that
-- end_date follows start_date, and keyed on (company, pharmacy) so a
-- branch could never renew a contract with the same manufacturer.
-- ---------------------------------------------------------------------
CREATE TABLE nova.supply_contract (
    contract_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   bigint      NOT NULL REFERENCES nova.company(company_id) ON DELETE CASCADE,
    branch_id    bigint      NOT NULL REFERENCES nova.branch(branch_id)   ON DELETE CASCADE,
    valid_period daterange   NOT NULL,
    terms        text,
    supervisor   text,
    created_at   timestamptz NOT NULL DEFAULT now(),

    -- One active contract per (company, branch) at any instant, but renewals
    -- over time are allowed. The original PK made renewal impossible.
    CONSTRAINT supply_contract_no_overlap
        EXCLUDE USING gist (company_id WITH =, branch_id WITH =, valid_period WITH &&)
);

-- ---------------------------------------------------------------------
-- Assortment / price list
-- Was: Pharmacy_Sells (legacy:155-164), which stored a single current
-- price with no history. Price history is required for demand modelling:
-- a price change is a demand driver, and a model that sees only today's
-- price cannot learn elasticity.
-- ---------------------------------------------------------------------
CREATE TABLE nova.branch_drug_price (
    branch_id      bigint      NOT NULL REFERENCES nova.branch(branch_id) ON DELETE CASCADE,
    drug_id        bigint      NOT NULL REFERENCES nova.drug(drug_id)     ON DELETE CASCADE,
    effective_from date        NOT NULL,
    effective_to   date,
    price          numeric(10,2) NOT NULL,

    PRIMARY KEY (branch_id, drug_id, effective_from),
    CONSTRAINT price_positive CHECK (price > 0),
    CONSTRAINT price_period_order CHECK (effective_to IS NULL OR effective_to > effective_from)
);

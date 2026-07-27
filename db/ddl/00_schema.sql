-- =====================================================================
-- NOVA · Layer 0 (OLTP) · Schemas, extensions, roles
-- PostgreSQL 16+
--
-- Ported from the original Oracle PL/SQL (see legacy/NOVA_DB.sql).
-- Rationale for the port: docs/DECISIONS.md D-002.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- digest() for identifier hashing
CREATE EXTENSION IF NOT EXISTS btree_gist;    -- exclusion constraints on ranges

-- nova       : operational tables the application reads and writes
-- nova_admin : secrets and configuration; no application role may read this
CREATE SCHEMA IF NOT EXISTS nova;
CREATE SCHEMA IF NOT EXISTS nova_admin;

-- ---------------------------------------------------------------------
-- Roles
--   nova_app      : read/write OLTP. Cannot read the PII salt.
--   nova_analyst  : read-only, and only through de-identified views.
--   nova_llm      : read-only, deliberately minimal. Used by the P11
--                   text-to-SQL agent so a generated statement physically
--                   cannot write. Least privilege is the guardrail; prompt
--                   instructions are not.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nova_app') THEN
        CREATE ROLE nova_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nova_analyst') THEN
        CREATE ROLE nova_analyst NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nova_llm') THEN
        CREATE ROLE nova_llm NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA nova TO nova_app, nova_analyst, nova_llm;
REVOKE ALL ON SCHEMA nova_admin FROM PUBLIC;

-- ---------------------------------------------------------------------
-- PII salt.
--
-- The original schema used Aadhaar (a national ID) as the PRIMARY KEY of
-- both Patient and Doctor (legacy/NOVA_DB.sql:96, :112). That propagates a
-- government identifier into every foreign key, every index and every join
-- in the database. Here identifiers are hashed with a salt that lives in a
-- schema no application role can read, and tables key on surrogate BIGINTs.
--
-- The salt is injected at init time from the NOVA_PII_SALT environment
-- variable; the fallback exists only so a cold `docker compose up` works,
-- and is not a secret worth protecting because the data is synthetic.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nova_admin.crypto_config (
    key        text PRIMARY KEY,
    value      text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO nova_admin.crypto_config (key, value)
VALUES ('pii_salt', 'dev-only-salt-replace-in-any-real-deployment')
ON CONFLICT (key) DO NOTHING;

-- SECURITY DEFINER: callers may hash an identifier without being able to
-- SELECT the salt themselves.
CREATE OR REPLACE FUNCTION nova.hash_national_id(p_raw text)
RETURNS bytea
LANGUAGE sql
SECURITY DEFINER
SET search_path = nova_admin, pg_temp
STABLE
AS $$
    SELECT digest(
        (SELECT value FROM nova_admin.crypto_config WHERE key = 'pii_salt') || p_raw,
        'sha256'
    );
$$;

COMMENT ON FUNCTION nova.hash_national_id(text) IS
    'Salted SHA-256 of a national identifier. Salt is not readable by application roles.';

# PII Policy

All data in this repository is **synthetic**. No real patient, prescriber or
transaction data has ever been loaded. This policy exists because a system that
handles this data *shape* in production would be subject to India's DPDP Act 2023 and,
in a US deployment, HIPAA — and because the original schema demonstrated exactly the
failure modes those regimes exist to prevent.

## What was wrong in the original schema

```sql
CREATE TABLE Doctor (
    aadhar_id VARCHAR2(12) PRIMARY KEY,   -- legacy/NOVA_DB.sql:96
    ...
CREATE TABLE Patient (
    aadhar_id VARCHAR2(12) PRIMARY KEY,   -- legacy/NOVA_DB.sql:112
    ...
    age NUMBER,
```

Four distinct problems:

1. **A national identifier as a primary key.** Aadhaar propagated into
   `Prescription`, `Drugs_Prescribed`, and every index and query plan touching them.
   The identifier could not be rotated, redacted, or deleted without rewriting the
   graph of foreign keys — which makes a data-subject erasure request structurally
   impossible to honour.
2. **Plaintext at rest.** Any user with `SELECT` on the table read every identifier.
3. **No access control.** No roles, no RLS. Every connected session saw every row.
4. **Mutable derived data.** `age NUMBER` is wrong the day after it is written, and
   because no `as_of` was recorded, it cannot be corrected retroactively.

## What the redesign does

| Control | Implementation |
|---|---|
| **Surrogate keys** | `patient_id`/`prescriber_id` are `BIGINT` identities. The national ID appears in no foreign key. |
| **Salted hashing** | `nova.hash_national_id()` — SHA-256 over a salt held in `nova_admin`, a schema no application role can read. `SECURITY DEFINER` lets callers hash without reading the salt. |
| **Raw value never stored** | `add_patient()`/`add_prescriber()` accept the raw ID, hash it inline, and store only the digest plus last-4 for support-desk disambiguation. |
| **Generalisation** | Birth *year*, not date of birth. Views expose age bucketed to decades. |
| **De-identified views** | `v_patient_deid`, `v_prescriber_deid` carry no name and no hash. |
| **Least privilege** | `nova_analyst` and `nova_llm` are granted the views and explicitly `REVOKE`d from base tables. |
| **Row-level security** | Branch-scoped policies on inventory, prescriptions and dispenses; fail-closed when the session variable is unset. |
| **Read-only LLM role** | `nova_llm` has `default_transaction_read_only = on` and a 10s statement timeout. A generated statement cannot write because the *role* forbids it — not because a prompt asked nicely. |

## Honest limitations

- **A salted hash is pseudonymisation, not anonymisation.** The Aadhaar space is
  small enough that an attacker holding both the salt and a candidate list can
  brute-force it. Real deployment needs an HSM-backed keyed MAC and salt rotation.
  Under DPDP and HIPAA, hashed identifiers remain personal data.
- **The `last4` column is a deliberate re-identification risk** accepted for
  operational usability. In a real deployment it should sit behind a separate,
  audited privilege.
- **Age bucketing alone is not k-anonymity.** Bucketed age + region + a prescription
  date can still be near-unique in a sparse cohort. Proper treatment needs
  k-anonymity or differential privacy on the analytics layer.
- **RLS is written but not executed** — no Postgres was available on the build
  machine (D-005). The policies are unverified until someone runs
  `docker compose up && make db-test`.
- **No audit logging.** Both regimes expect access logs on personal data. Not built.

These are stated rather than solved because a portfolio project that claims
regulatory compliance it has not tested is worse than one that maps its own gaps.

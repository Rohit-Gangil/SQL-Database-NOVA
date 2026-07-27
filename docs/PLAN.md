# Phase Plan

Every phase below has an objectively checkable **Definition of Done (DoD)**. A phase
is not complete until a command in the repo demonstrates it. "It looks right" is not
a DoD.

**Target repo layout**

```
SQL-Database-NOVA/
├── legacy/                  # original Oracle scripts, preserved unmodified
├── db/
│   ├── ddl/                 # PostgreSQL schema, split by concern
│   ├── functions/           # PL/pgSQL replacements for the 24 procedures
│   ├── indexes/             # index DDL + EXPLAIN ANALYZE evidence
│   └── policies/            # row-level security, roles, PII views
├── nova/                    # the Python package
│   ├── simulator/           # P3  demand-generating process
│   ├── warehouse/           # P4  dbt project + Dagster defs
│   ├── features/            # P5  point-in-time feature builders
│   ├── forecast/            # P6  model ladder + reconciliation
│   ├── inventory/           # P6  newsvendor / order-quantity policy
│   ├── anomaly/             # P7  graph anomaly detection
│   ├── causal/              # P8  uplift + experimentation
│   ├── serving/             # P9  FastAPI app
│   ├── monitoring/          # P10 drift + retraining triggers
│   └── llm/                 # P11 text-to-SQL + eval harness
├── tests/
├── docs/
├── docker-compose.yml
├── Makefile
└── pyproject.toml
```

---

## P2 — Harden the OLTP layer

**Objective.** Make Layer 0 something a reviewer can run in under a minute and a
forecasting system can actually read from. Today it can do neither.

**Deliverables**
- `legacy/` — the four original Oracle `.sql` files, moved unmodified (provenance)
- `db/ddl/01_schema.sql` … `db/ddl/06_inventory.sql` — PostgreSQL DDL
- `db/functions/*.sql` — PL/pgSQL ports of the 24 procedures
- `db/indexes/01_indexes.sql` + `docs/PERF.md` — measured `EXPLAIN ANALYZE` before/after
- `db/policies/01_rls.sql`, `docs/PII-POLICY.md`
- `docker-compose.yml`, `db/Makefile` targets

**Approach.** The single most important structural fix is the `Stock` table. Today
([legacy `NOVA_DB.sql:103-108`](../legacy/NOVA_DB.sql#L103-L108)) it is:

```sql
CREATE TABLE Stock (
    pharmacy_1 VARCHAR2(100) PRIMARY KEY,   -- one row per pharmacy, ever
    stock      VARCHAR2(100)                -- inventory as a *string*
);
```

That cannot represent "how many units of drug D does branch B hold on date T" — which
is the only question the entire project depends on. It is replaced by an inventory
ledger keyed `(branch, drug, as_of_date)` carrying `qty_on_hand`, `reorder_point`,
`lead_time_days`, and expiry-lot tracking.

Other fixes: dedupe the DROP blocks duplicated at `NOVA_DB.sql:22-73`; remove the
`COMMIT` inside every procedure (a callee that commits cannot be composed into a
transaction); replace `EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT.PUT_LINE(...)` — which
swallows the error and returns success — with raised exceptions; replace Aadhaar as a
natural primary key with surrogate BIGINT keys plus a salted hash, since a national ID
as a PK leaks identity through every foreign key in the schema.

**Rejected:** keeping Oracle and shipping a Docker Oracle XE image (licensing friction,
2GB+ image, slow cold start); an ORM-first rewrite (throws away the SQL work, which is
a genuine asset of this repo).

**DoD**
1. `docker compose up -d` on a cold clone → healthy Postgres in < 60s
2. `make db-init` creates schema, functions, indexes, policies with zero errors
3. `make db-test` passes — every ported function has at least one assertion, including
   failure paths that must now raise
4. `docs/PERF.md` contains real `EXPLAIN ANALYZE` output before and after indexing
5. No natural-person identifier is stored in plaintext; RLS demonstrably blocks a
   cross-branch read in a test
6. README no longer claims triggers that do not exist

**Risks.** PL/pgSQL semantics differ from PL/SQL around exceptions and implicit
transactions → mitigated by a test per function rather than a visual port.

**Effort:** ~1 week equivalent.

---

## P3 — Data simulator

**Objective.** Produce 5M+ transaction rows whose generating process we control, so
every downstream claim is measurable against known truth.

**Deliverables:** `nova/simulator/` (demand process, prescriber personas, anomaly
injection, supply shocks), `make simulate`, `docs/SIMULATOR.md` documenting the DGP.

**Approach.** Demand per `(branch, drug, day)` is a compound process: a Bernoulli
occurrence with drug- and branch-specific rate, times a size distribution
(negative binomial), modulated by multiplicative seasonality (weekly + annual, e.g.
antibiotics in monsoon, antihistamines in spring), a slow trend, and a product
lifecycle (launch ramp, generic cannibalization). Roughly 70–85% of cells must be
zero or the intermittency claim is fake.

Injected, with recorded ground truth in a held-out table:
- **Anomalous prescribers** (~1.5%) — over-prescribing controlled substances
- **Supply shocks** — a manufacturer offline 2–4 weeks, forcing substitution
- **Demand regime changes** — for drift detection in P10 to have something to detect

Anchored to reality via public vocabularies (RxNorm, openFDA) for SKU metadata.

**Rejected:** a static public dataset (no ground truth for anomalies, no controllable
stress tests, and no public *pharmacy-branch-level* dataset of adequate granularity
exists); a pure random walk (no intermittency, trivially forecastable).

**DoD**
1. `make simulate` reproduces a byte-identical dataset from a fixed seed
2. ≥ 5,000,000 rows in `fact_demand`
3. Zero-cell proportion between 0.65 and 0.90 — asserted in a test
4. Seasonality recoverable: STL decomposition on aggregate series shows the injected
   annual period within tolerance — asserted in a test
5. Ground-truth anomaly labels exist and are excluded from all model training inputs
6. `docs/SIMULATOR.md` states every distribution and parameter

**Effort:** ~1.5 weeks.

---

## P4 — Warehouse + orchestration

**Objective.** Turn OLTP rows into an analytics-shaped star schema, on a schedule,
with tests that fail loudly.

**Deliverables:** dbt project (`staging` → `intermediate` → `marts`), Dagster
definitions, dbt tests + Great Expectations suite, `make warehouse`.

**Approach.** Star schema: `fct_demand`, `fct_inventory_snapshot`, `fct_replenishment`
against `dim_branch`, `dim_drug`, `dim_date`, `dim_prescriber`. DuckDB as the
analytics engine (zero-ops, fast, runs in CI) reading from Postgres.

**DoD**
1. `make warehouse` builds all models from a clean state
2. `dbt test` passes; ≥ 1 test per mart model, including a row-count reconciliation
   between source and mart
3. A deliberately corrupted row makes CI fail (proven by a test that injects one)
4. Dagster asset graph renders and materializes end-to-end

**Effort:** ~1 week.

---

## P5 — Point-in-time-correct feature layer

**Objective.** Guarantee no feature uses information unavailable at prediction time.
This is the phase that decides whether every number in P6 is real or fiction.

**Deliverables:** `nova/features/`, `docs/LEAKAGE.md`, a leakage test suite.

**Approach.** Every feature is defined as a function of `(entity, as_of_timestamp)`
and may only read records with `event_time <= as_of - lag`. Lags respect realistic
data-availability delays: yesterday's sales are not available at 00:00 today.

**DoD**
1. A **leakage test** that shifts a target forward and asserts feature values do not
   change — this test must exist and pass
2. Every feature declares its `event_time` and availability lag in code, not comments
3. `docs/LEAKAGE.md` explains the splitting strategy in prose a reviewer can audit

**Effort:** ~4 days.

---

## P6 — FLAGSHIP: hierarchical forecasting → inventory optimization

**Objective.** The centerpiece. Beat a dumb baseline honestly, then convert the
forecast into an order quantity and show the money.

**Deliverables:** `nova/forecast/` (model ladder), `nova/inventory/` (policy),
`docs/RESULTS.md` (baselines table with error bars, ablation), `make train`,
`make backtest`.

**Approach — the ladder, each rung must beat the previous or be reported as not
beating it:**

| Rung | Model | Why it is here |
|---|---|---|
| 0 | Naive / seasonal-naive | The honest floor |
| 1 | Croston / SBA / TSB | The intermittent-demand classic |
| 2 | LightGBM, global, with lags + calendar + hierarchy features | The strong practical baseline that usually wins |
| 3 | TFT or N-BEATS | Tests whether deep learning earns its cost here |

Forecasts are **probabilistic** (quantiles), not point — because the decision layer
needs a distribution. Evaluation by **rolling-origin backtesting** on time-based
splits only. Hierarchical reconciliation (MinT or OLS) so SKU → branch → region →
national sums are coherent.

Then the part that makes it a decision system: a **newsvendor** order quantity per
SKU, using the drug-specific ratio of understock penalty to overstock cost, extended
for perishability, compared head-to-head against the incumbent fixed-reorder-point
policy in a simulated rollout.

**Rejected:** one model per series (does not scale to thousands of SKUs, no
cross-learning); point forecasts only (cannot drive a cost-optimal decision).

**DoD**
1. `make backtest` reproduces every number in `docs/RESULTS.md`
2. Baselines table shows all four rungs with confidence intervals from multiple
   backtest origins — **including the honest result if deep learning loses to LightGBM**
3. Probabilistic calibration reported (does the 90% interval contain truth ~90% of
   the time?)
4. Hierarchical coherence asserted in a test: child forecasts sum to parent
5. Head-to-head total-cost comparison vs. incumbent policy, in ₹, with the simulation
   assumptions stated
6. Ablation table: contribution of each feature group

**Effort:** ~3 weeks. This is the phase to protect if time runs short.

---

## P7 — Graph anomaly detection

**Objective.** Find the injected bad actors, and report precision honestly.

**Approach.** Prescriber–patient–drug bipartite graph. Isolation Forest on tabular
aggregates as baseline → GNN (PyTorch Geometric) node-level anomaly scoring.

**DoD:** precision@k and recall@k against P3 ground truth, at k ∈ {10, 50, 100};
GNN compared against the Isolation Forest baseline with the honest result reported;
ground-truth labels provably absent from training features.

**Effort:** ~1.5 weeks.

---

## P8 — Causal inference + experimentation

**Objective.** Answer "does the intervention *cause* the improvement" — the question
FAANG product-DS interviews are built around.

**Approach.** Propensity-score modelling and matching; difference-in-differences on
the simulated intervention; uplift/CATE modelling (EconML) to identify whom to target;
refutation tests (placebo treatment, random common cause) via DoWhy. Plus a small
experimentation module: fixed-horizon and sequential tests, with CUPED variance
reduction.

**DoD:** the simulator's known true treatment effect is recovered within the
estimator's stated CI — this is the check that a real dataset could never give;
DoWhy refutation tests reported including failures; CUPED demonstrably reduces
variance vs. the unadjusted estimator; assumptions and their violations documented.

**Effort:** ~1.5 weeks.

---

## P9 — Serving

**Objective.** Make it a system, not a notebook.

**Approach.** FastAPI, models exported to ONNX, batch and single-item endpoints,
feature lookup from the online store, `/health` and `/metrics`.

**DoD:** measured p50/p95/p99 latency and QPS from an actual load test (Locust or k6)
with the hardware stated; cost per 1k predictions computed from measured throughput;
ONNX output verified numerically equivalent to the training-time model in a test.
**No latency number appears that was not measured.**

**Effort:** ~1 week.

---

## P10 — Monitoring & retraining

**Approach.** Evidently for data/prediction drift against a reference window; explicit
alert thresholds; a retraining trigger that fires on drift or scheduled staleness;
MLflow for experiment tracking; DVC for data/model versioning.

**DoD:** feeding the P3 regime-change window through the monitor raises an alert
(demonstrated in a test); a champion/challenger gate blocks promotion of a worse
model; MLflow run history reproduces the reported results.

**Effort:** ~1 week.

---

## P11 — LLM layer

**Objective.** Not a chatbot demo. An evaluated NL→SQL interface over the real schema.

**Approach.** Text-to-SQL over the P2 schema with a read-only role, statement timeout
and cost ceiling; RAG over drug-information documents with citations.

**DoD:** **≥100 hand-written (question, gold SQL) pairs** in `nova/llm/eval/`;
reported **execution accuracy** (result-set equivalence, not string match); a
prompt-injection test suite that must show zero successful writes; ablation of
retrieval-augmented schema linking vs. naive full-schema prompting.

**Effort:** ~1.5 weeks.

---

## P12 — Engineering hygiene

**Deliverables:** pytest suite, GitHub Actions CI (ruff + mypy + pytest + dbt test),
Dockerfile, Makefile, pinned dependencies, `.gitattributes`, pre-commit.

**DoD:** CI green on the feature branch; CI fails on a deliberately introduced lint
error, type error, and test failure (each proven once); `make setup && make test`
works on a cold clone; no dependency unpinned.

**Effort:** ~4 days.

---

## P13 — Communication

**Deliverables:** rewritten README (architecture diagram, results tables with error
bars, ablation, model cards, Limitations), `docs/BLOG.md`, deployed demo.

**DoD:** every number in the README traceable to a `make` target; Limitations section
names the synthetic-data caveat explicitly and without softening; original coursework
vs. solo extension clearly delineated for attribution; demo URL live at the top.

**Effort:** ~4 days.

---

## Sequencing and what to protect

Critical path: **P2 → P3 → P4 → P5 → P6**. Everything else is additive.
If time runs short, P7–P11 are deferred before P6 is compromised; a rigorously
evaluated forecasting-to-decision system with real engineering hygiene is worth more
than five half-finished model families.

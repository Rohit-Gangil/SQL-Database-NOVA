# NOVA — Pharmacy Replenishment Decision System

> Predicts, for every drug at every branch of a pharmacy chain, how much demand is
> coming and how many units to reorder — so branches stop running out of drugs
> patients need and stop destroying drugs that expire on the shelf.

**The deliverable is an order quantity, not a prediction.** A forecast that does not
change what gets ordered has no value, so the headline metric is total cost in ₹,
not WAPE.

📊 **[Results with error bars →](docs/RESULTS.md)**  ·  🧪 **[How the data is generated →](docs/SIMULATOR.md)**  ·  🔒 **[Leakage controls →](docs/LEAKAGE.md)**

## Headline

| | Incumbent fixed-ROP | NOVA (newsvendor + LightGBM) |
|---|---:|---:|
| Fill rate | 97.74% | **99.74%** |
| Units unmet (184 days) | 17,410 | **2,041** (−88%) |
| Total cost | ₹2,080,639 | **₹401,010 (−80.7%)** |

**The interesting part is where that saving came from.** LightGBM beat the best
classical baseline by only **1.6% WAPE** — because the irreducible-error floor on this
data is WAPE 0.883 and the best classical method was already at 0.907. There was only
0.024 of reducible error available, and the model captured 59% of it.

Almost all the value came from the **decision layer**, not a better model: replacing
one chain-wide safety factor with a per-SKU newsvendor critical ratio. The direction
holds across a 16× sweep of the key cost assumption (−54% to −90%); the specific
percentage does not, and [docs/RESULTS.md](docs/RESULTS.md) says so in those words.

A negative result kept in the table: **training on the censoring-corrected target made
WAPE slightly worse** (0.8928 vs 0.8854) while cutting forecast bias 4× (−0.062 →
−0.015). For a system whose output is an order quantity, that is the right trade —
a systematically low forecast under-orders, causes a stockout, and feeds on itself.

---

## Why this problem

Drug shortages and expiry waste are two sides of one decision, and both are expensive.
As of April 2025 there were ~270 active drug shortages in the US; a Vizient survey put
the labour cost of managing them at **~$900M/year** across US hospitals, more than
double the 2019 figure. On the other side, industry-average drug expiry waste runs
**2–3% of inventory value** — $200k–$700k a year for a $10M drug budget.

These pull in opposite directions, which makes this an **asymmetric-cost decision
under uncertainty**, not a regression exercise. Sources and full framing:
[docs/00-PROBLEM.md](docs/00-PROBLEM.md).

What makes it genuinely hard:

- **Demand is intermittent.** 74% of `(branch, drug, day)` cells are zero; 94% of
  series are "lumpy" under Syntetos–Boylan, the regime where classical exponential
  smoothing fails outright.
- **Demand is censored.** Observed sales are `min(demand, stock)`. A model trained on
  sales learns that a stockout day had low demand, forecasts lower, and causes the
  next stockout.
- **Stock perishes.** Over-ordering doesn't just cost carrying charges; it expires.
- **The cost of error is SKU-specific.** Running out of an anticoagulant is not the
  same error as running out of a vitamin — so one chain-wide safety factor cannot be
  right.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  L6  Report      docs/RESULTS.md generated from artifacts    │
├──────────────────────────────────────────────────────────────┤
│  L5  Decision    newsvendor critical ratio -> order quantity │
│                  nova/inventory/                             │
├──────────────────────────────────────────────────────────────┤
│  L4  Models      naive -> Croston/SBA/TSB -> LightGBM        │
│                  rolling-origin backtest · nova/forecast/    │
├──────────────────────────────────────────────────────────────┤
│  L3  Features    point-in-time correct, leakage-tested       │
│                  nova/features/                              │
├──────────────────────────────────────────────────────────────┤
│  L2  Warehouse   star schema + 11 data-quality checks        │
│                  nova/warehouse/                             │
├──────────────────────────────────────────────────────────────┤
│  L1  Simulator   5.9M series-days, known ground truth        │
│                  nova/simulator/                             │
├──────────────────────────────────────────────────────────────┤
│  L0  OLTP        PostgreSQL schema, RLS, PII controls        │
│                  db/  (ported from the original Oracle)      │
└──────────────────────────────────────────────────────────────┘
```

## Quickstart

```bash
pip install -e ".[dev]"
make all          # simulate -> warehouse -> features -> backtest -> policy -> results
```

Roughly 8 minutes end to end on a laptop. Then read [docs/RESULTS.md](docs/RESULTS.md) —
every number in it was written by `make results` from measured artifacts, never by hand.

```bash
make test         # full suite
make lint         # ruff
make db-up        # PostgreSQL Layer 0 (see caveat below)
```

## What makes this different from a notebook

**Every rung of the ladder is compared to the one below it, with error bars.**
Naive → seasonal naive → trailing mean → Croston → SBA → TSB → LightGBM, evaluated
over 6 rolling origins. Results include an **oracle row** — the generating process's
own conditional mean — so you can see how much of the remaining error is irreducible
rather than just how good the model looks in isolation.

**Leakage is tested, not promised.** `tests/test_leakage.py` corrupts every target
value after a cutoff, rebuilds features with the production SQL, and asserts nothing
before the cutoff moved. It caught a real leak in the hierarchy features: `LAG()` was
applied after joining to branch-level rows, so with tied dates it returned a sibling
branch's *same-day* total. That bug is invisible by inspection and would have inflated
every downstream number.

**The baseline was calibrated so it isn't a straw man.** The incumbent policy's safety
factor was swept until it landed at 92% fill rate and 1.5% expiry waste — where real
chains operate. Beating an incompetent baseline proves nothing. The sweep is in
[docs/SIMULATOR.md](docs/SIMULATOR.md), including two bugs it exposed.

**Negative results stay in.** Where a model fails to beat the rung below, the table
says so.

## Layer 0: what changed from the original coursework

This repository began as an Oracle DBMS course project. The original scripts are
preserved unmodified in [`legacy/`](legacy/). The most consequential fix:

```sql
-- BEFORE (legacy/NOVA_DB.sql:103-108)
CREATE TABLE Stock (
    pharmacy_1 VARCHAR2(100) PRIMARY KEY,  -- one row per pharmacy, ever
    stock      VARCHAR2(100)               -- inventory as a *string*
);
```

No drug column, no date column, no numeric quantity — it could not answer "how many
units of drug D does branch B hold on date T", which is the only question this project
depends on. (The original `pharmacy_stock` procedure never read it anyway; it read the
price list and reported that as stock.)

Replaced by `inventory_lot` (expiry tracking), `inventory_snapshot` (daily ledger with
a CHECK-enforced flow identity), and `replenishment_order` (records which policy
produced each order).

Other Layer 0 work:

| | |
|---|---|
| **Dispense table** | Absent originally. Records unmet demand, making stockouts measurable. |
| **Errors raise** | All 24 procedures ended in `EXCEPTION WHEN OTHERS THEN DBMS_OUTPUT...` — printing to a console buffer and then returning *successfully*. |
| **No `COMMIT` in callees** | Every original procedure committed, so nothing could be composed into a transaction. |
| **PII** | Aadhaar was the PRIMARY KEY of `Patient` and `Doctor` in plaintext, propagating a national ID into every foreign key. Now surrogate keys + salted SHA-256 + de-identified views + RLS. See [docs/PII-POLICY.md](docs/PII-POLICY.md). |
| **Reports return sets** | The six report procedures printed to `DBMS_OUTPUT`; nothing could consume them. |
| **Indexes** | The original had none beyond primary keys. |

## Honest status

I would rather this section be read than skipped.

**Verified — runs and is measured on this machine:**
the simulator, the warehouse and its 11 data-quality checks, the feature layer and
its leakage tests, the forecasting ladder, the newsvendor policy comparison, and the
generated results document.

**Written but UNVERIFIED — the PostgreSQL Layer 0.** The build machine has no Docker
and no `psql`, so `db/*.sql` and `docker-compose.yml` have never been executed. They
are the intended production path and are written to be correct, but until someone
runs `make db-up && make db-init` they should be treated as unreviewed code. No
`EXPLAIN ANALYZE` numbers are reported anywhere, because none were measured.

**Not built** (deferred, per the plan's own rule that the flagship is protected
first — [docs/DECISIONS.md](docs/DECISIONS.md) D-006):

| Phase | Status |
|---|---|
| Rung 3 — TFT / N-BEATS | Not built. No GPU; torch out of scope this pass. |
| Hierarchical reconciliation (MinT/OLS) | **Not built**, though P1 planned it. The hierarchy rollups and coherence checks exist in the warehouse, but forecasts are produced per series and are not reconciled. |
| P7 — GNN anomaly detection | Not built. Ground-truth labels **are** generated and ready. |
| P8 — Causal inference / uplift | Not built. True treatment effect **is** generated. |
| P9 — FastAPI + ONNX serving | Not built. No latency numbers are claimed. |
| P10 — Drift monitoring | Not built. Regime changes **are** injected and labelled. |
| P11 — Text-to-SQL + eval harness | Not built. The read-only `nova_llm` role exists. |

**The data is synthetic.** All of it. No real patient data has ever been loaded.
This is a deliberate choice — it is what makes precision against known ground truth
measurable at all — and it is also the single biggest limitation: these results show
the methods work on data whose generating process I control. They are not evidence of
real-world performance.

## Repository layout

```
db/          PostgreSQL Layer 0: DDL, PL/pgSQL functions, indexes, RLS
legacy/      the original Oracle coursework, unmodified
nova/
  simulator/ demand-generating process + incumbent inventory policy
  warehouse/ star schema + data-quality checks
  features/  point-in-time feature construction
  forecast/  model ladder, metrics, rolling-origin backtest
  inventory/ newsvendor policy and cost comparison
  report/    generates docs/RESULTS.md
tests/       simulator, leakage, and metric tests
docs/        problem, plan, decisions, simulator, leakage, results, PII policy
```

## Attribution

The original Oracle DBMS coursework (preserved in [`legacy/`](legacy/)) was by
**Aadi Deshmukh, Aaditya Bhagat, Rohit Gangil, and Vikhyat Singh**.

Everything outside `legacy/` — the Postgres port, simulator, warehouse, feature layer,
forecasting ladder, decision layer, tests, and documentation — is solo work by
**Rohit Gangil**, on the `feature/nova-ml-platform` branch.

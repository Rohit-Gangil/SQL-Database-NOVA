"""Build the analytics marts and run data-quality checks.

    python -m nova.warehouse.build

Quality checks are not advisory. `--strict` exits non-zero on any failure so
CI fails on bad data rather than training a model on it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

from nova.config import DUCKDB_PATH

MODELS_SQL = Path(__file__).parent / "models.sql"


# ---------------------------------------------------------------------
# Data-quality checks.
#
# Each is a SQL predicate that must return zero rows. Phrased as "find the
# broken rows" rather than "assert a count", so a failure can be inspected
# directly by running the same query.
# ---------------------------------------------------------------------
CHECKS: list[tuple[str, str]] = [
    (
        "fct_demand_daily: no negative quantities",
        """SELECT * FROM mart.fct_demand_daily
           WHERE units_sold < 0 OR units_unmet < 0 OR qty_close < 0""",
    ),
    (
        "fct_demand_daily: ledger flow identity holds",
        """SELECT * FROM mart.fct_demand_daily
           WHERE qty_open + qty_received - units_sold - qty_expired <> qty_close""",
    ),
    (
        "fct_demand_daily: unmet demand implies empty shelf",
        """SELECT * FROM mart.fct_demand_daily
           WHERE units_unmet > 0 AND qty_close <> 0""",
    ),
    (
        "fct_demand_daily: grain is unique on (branch, drug, date)",
        """SELECT branch_id, drug_id, date_key, COUNT(*) n
           FROM mart.fct_demand_daily GROUP BY 1,2,3 HAVING COUNT(*) > 1""",
    ),
    (
        "fct_demand_daily: every drug resolves to a dimension row",
        """SELECT DISTINCT f.drug_id FROM mart.fct_demand_daily f
           LEFT JOIN mart.dim_drug d USING (drug_id) WHERE d.drug_id IS NULL""",
    ),
    (
        "fct_demand_daily: every branch resolves to a dimension row",
        """SELECT DISTINCT f.branch_id FROM mart.fct_demand_daily f
           LEFT JOIN mart.dim_branch b USING (branch_id) WHERE b.branch_id IS NULL""",
    ),
    (
        "fct_demand_daily: no date gaps within a series",
        """WITH bounds AS (
               SELECT branch_id, drug_id, MIN(date_key) lo, MAX(date_key) hi,
                      COUNT(*) n
               FROM mart.fct_demand_daily GROUP BY 1,2
           )
           SELECT * FROM bounds WHERE n <> DATE_DIFF('day', lo, hi) + 1""",
    ),
    (
        "hierarchy: region rollup reconciles to branch level",
        """WITH b AS (SELECT date_key, drug_id, SUM(units_demanded_observed) u
                      FROM mart.fct_demand_daily GROUP BY 1,2),
                r AS (SELECT date_key, drug_id, SUM(units_demanded_observed) u
                      FROM mart.fct_demand_region GROUP BY 1,2)
           SELECT b.date_key, b.drug_id, b.u, r.u
           FROM b JOIN r USING (date_key, drug_id) WHERE b.u <> r.u""",
    ),
    (
        "hierarchy: national rollup reconciles to branch level",
        """WITH b AS (SELECT date_key, drug_id, SUM(units_demanded_observed) u
                      FROM mart.fct_demand_daily GROUP BY 1,2)
           SELECT b.date_key, b.drug_id, b.u, n.units_demanded_observed
           FROM b JOIN mart.fct_demand_national n USING (date_key, drug_id)
           WHERE b.u <> n.units_demanded_observed""",
    ),
    (
        "dim_series: demand classification is exhaustive",
        """SELECT * FROM mart.dim_series WHERE demand_class IS NULL""",
    ),
    (
        "leakage guard: no truth column reached the marts",
        """SELECT table_name, column_name
           FROM information_schema.columns
           WHERE table_schema = 'mart'
             AND (column_name ILIKE '%_true%' OR column_name ILIKE 'mu_%')""",
    ),
]


def build(con: duckdb.DuckDBPyConnection) -> None:
    sql = MODELS_SQL.read_text(encoding="utf-8")
    t0 = time.perf_counter()
    con.execute(sql)
    print(f"[warehouse] models built            {time.perf_counter() - t0:6.2f}s")


def run_checks(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int]]:
    failures: list[tuple[str, int]] = []
    for name, query in CHECKS:
        n = len(con.execute(query).fetchall())
        status = "PASS" if n == 0 else f"FAIL ({n} rows)"
        print(f"  [{status:>14}] {name}")
        if n:
            failures.append((name, n))
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any data-quality check fails")
    args = ap.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH))
    build(con)

    print("\n[warehouse] data-quality checks")
    failures = run_checks(con)

    counts = con.execute("""
        SELECT 'fct_demand_daily' t, COUNT(*) n FROM mart.fct_demand_daily
        UNION ALL SELECT 'fct_demand_region', COUNT(*) FROM mart.fct_demand_region
        UNION ALL SELECT 'fct_demand_national', COUNT(*) FROM mart.fct_demand_national
        UNION ALL SELECT 'dim_series', COUNT(*) FROM mart.dim_series
    """).fetchall()
    print("\n[warehouse] row counts")
    for t, n in counts:
        print(f"  {t:<22} {n:>12,}")

    classes = con.execute("""
        SELECT demand_class, COUNT(*) n,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) pct
        FROM mart.dim_series GROUP BY 1 ORDER BY n DESC
    """).fetchall()
    print("\n[warehouse] demand classification (Syntetos-Boylan)")
    for c, n, pct in classes:
        print(f"  {c:<14} {n:>7,}  {pct:>5}%")

    con.close()

    if failures:
        print(f"\n{len(failures)} data-quality check(s) FAILED")
        return 1 if args.strict else 0
    print("\nAll data-quality checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

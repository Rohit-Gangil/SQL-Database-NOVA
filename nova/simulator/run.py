"""Simulator entry point: builds the full synthetic dataset into DuckDB.

    python -m nova.simulator.run            # default size (~5.9M series-days)
    python -m nova.simulator.run --small    # fast smoke run for CI

Everything is seeded from `nova.config.SEED`. Two runs on the same seed produce
identical data; that is asserted in tests/test_simulator.py rather than assumed.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import replace

import duckdb
import numpy as np
import pandas as pd

from nova.config import DATA_DIR, DUCKDB_PATH, SEED, SIM, SimConfig
from nova.simulator import anomalies, demand as demand_mod, entities, inventory


def _panel_to_frame(cfg: SimConfig, arrays: dict[str, np.ndarray],
                    true_demand: np.ndarray, mu: np.ndarray) -> pd.DataFrame:
    """Flatten the (branch, drug, day) cube into a tidy fact table."""
    n_b, n_d, n_t = true_demand.shape
    dates = pd.date_range(cfg.start_date, periods=n_t, freq="D")

    branch_ix = np.repeat(np.arange(1, n_b + 1, dtype=np.int32), n_d * n_t)
    drug_ix = np.tile(np.repeat(np.arange(1, n_d + 1, dtype=np.int32), n_t), n_b)
    date_ix = np.tile(dates.to_numpy(), n_b * n_d)

    frame = pd.DataFrame(
        {
            "branch_id": branch_ix,
            "drug_id": drug_ix,
            "as_of_date": date_ix,
            # `demand_true` and `mu_true` are the simulator's private truth.
            # They are written to a separate schema and must never enter a
            # feature set -- observed sales are all a real system would see.
            "demand_true": true_demand.reshape(-1),
            "mu_true": mu.reshape(-1).astype(np.float32),
        }
    )
    for name, arr in arrays.items():
        frame[name] = arr.reshape(-1)
    return frame


def build(cfg: SimConfig, seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()

    companies = entities.make_companies(cfg, rng)
    branches = entities.make_branches(cfg, rng)
    drugs = entities.make_drugs(cfg, rng, companies)
    prescribers = entities.make_prescribers(cfg, rng)
    patients = entities.make_patients(cfg, rng, branches, prescribers)
    print(f"[sim] entities                     {time.perf_counter() - t0:6.2f}s")

    t1 = time.perf_counter()
    regimes = demand_mod.generate_regime_changes(cfg, rng, drugs, branches)
    shocks = demand_mod.generate_supply_shocks(cfg, rng, companies, drugs)
    true_demand, mu = demand_mod.simulate_true_demand(cfg, rng, branches, drugs, regimes)
    print(f"[sim] true demand {true_demand.size:>10,} cells {time.perf_counter() - t1:6.2f}s")

    t2 = time.perf_counter()
    inv = inventory.simulate_inventory(cfg, rng, true_demand, drugs, shocks)
    print(f"[sim] inventory policy             {time.perf_counter() - t2:6.2f}s")

    t3 = time.perf_counter()
    anomalous = anomalies.choose_anomalous_prescribers(cfg, rng, prescribers)
    rx = anomalies.generate_prescriptions(
        cfg, rng, true_demand, branches, drugs, prescribers, patients, anomalous
    )
    print(f"[sim] prescriptions {len(rx):>9,} rows    {time.perf_counter() - t3:6.2f}s")

    t4 = time.perf_counter()
    panel = _panel_to_frame(cfg, inv, true_demand, mu)
    print(f"[sim] panel assembled {len(panel):>9,} rows  {time.perf_counter() - t4:6.2f}s")

    return {
        "company": companies,
        "branch": branches,
        "drug": drugs,
        "prescriber": prescribers,
        "patient": patients,
        "fact_demand": panel,
        "prescription": rx,
        "truth_anomalous_prescriber": anomalous,
        "truth_supply_shock": shocks,
        "truth_regime_change": regimes,
    }


def write_duckdb(tables: dict[str, pd.DataFrame], path=DUCKDB_PATH) -> None:
    """Persist to DuckDB, keeping simulator truth in a separate schema.

    `nova_truth` exists so that a feature query cannot reach a label by
    accident. Anything named `truth_*` lands there and nowhere else.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA IF NOT EXISTS nova")
    con.execute("CREATE SCHEMA IF NOT EXISTS nova_truth")

    for name, df in tables.items():
        if df is None or len(df) == 0:
            continue
        schema, tbl = ("nova_truth", name[6:]) if name.startswith("truth_") else ("nova", name)
        con.register("_tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE {schema}.{tbl} AS SELECT * FROM _tmp")
        con.unregister("_tmp")

    # The two truth columns riding along in fact_demand are split out and
    # dropped from the analytics table, so no model can consume them.
    con.execute("""
        CREATE OR REPLACE TABLE nova_truth.demand_true AS
        SELECT branch_id, drug_id, as_of_date, demand_true, mu_true
        FROM nova.fact_demand
    """)
    con.execute("ALTER TABLE nova.fact_demand DROP COLUMN demand_true")
    con.execute("ALTER TABLE nova.fact_demand DROP COLUMN mu_true")

    con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the NOVA synthetic dataset")
    ap.add_argument("--small", action="store_true",
                    help="fast reduced-size run for CI and smoke tests")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    cfg = SIM
    if args.small:
        cfg = replace(SIM, n_branches=6, n_drugs=25, n_patients=800,
                      n_prescribers=60, end_date=pd.Timestamp("2023-12-31").date())

    t0 = time.perf_counter()
    tables = build(cfg, seed=args.seed)
    write_duckdb(tables)

    panel = tables["fact_demand"]
    zero_frac = float((panel["qty_dispensed"] == 0).mean())
    unmet_rate = float((panel["qty_unmet"] > 0).mean())

    print("-" * 62)
    print(f"  rows in fact_demand : {len(panel):,}")
    print(f"  zero-sales cells    : {zero_frac:.1%}")
    print(f"  cells with unmet    : {unmet_rate:.2%}")
    print(f"  total elapsed       : {time.perf_counter() - t0:.1f}s")
    print(f"  written to          : {DUCKDB_PATH}")


if __name__ == "__main__":
    main()

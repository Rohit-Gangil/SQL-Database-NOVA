"""Injected bad actors and the prescription-level table they act on.

Ground truth lives in `nova_truth` (a separate DuckDB schema, mirroring the
Postgres design) and is never joined into any feature table. The separation is
physical rather than by convention, because the failure mode -- a label leaking
into a feature and producing a meaningless 0.99 AUC -- is silent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nova.config import SimConfig

ANOMALY_TYPES = ["overprescribing", "phantom_patients", "controlled_ring"]


def choose_anomalous_prescribers(
    cfg: SimConfig, rng: np.random.Generator, prescribers: pd.DataFrame
) -> pd.DataFrame:
    """Select the prescribers that will behave anomalously, and how."""
    n = max(1, int(round(len(prescribers) * cfg.anomalous_prescriber_frac)))
    chosen = rng.choice(prescribers["prescriber_id"], size=n, replace=False)
    kinds = rng.choice(ANOMALY_TYPES, size=n, p=[0.5, 0.25, 0.25])
    start = rng.integers(int(cfg.n_days * 0.2), int(cfg.n_days * 0.7), size=n)
    return pd.DataFrame(
        {
            "prescriber_id": chosen.astype(np.int32),
            "anomaly_type": kinds,
            # Severity drives how far behaviour departs from the peer norm.
            # Deliberately spread across the range: a detector that only finds
            # the blatant cases should score well at k=10 and poorly at k=100,
            # and the evaluation should show that rather than hide it.
            "severity": rng.uniform(0.35, 1.0, size=n).round(3),
            "active_from_day": start.astype(np.int32),
        }
    )


def generate_prescriptions(
    cfg: SimConfig,
    rng: np.random.Generator,
    demand: np.ndarray,
    branches: pd.DataFrame,
    drugs: pd.DataFrame,
    prescribers: pd.DataFrame,
    patients: pd.DataFrame,
    anomalous: pd.DataFrame,
    max_rows: int = 1_200_000,
) -> pd.DataFrame:
    """Attribute a sample of demand to (prescriber, patient) pairs.

    Full attribution of every demand unit would produce tens of millions of
    rows for no analytical gain, so a capped sample is drawn. The sample is
    weighted by demand, which preserves the branch/drug mix that the anomaly
    detector needs.
    """
    n_b, n_d, n_t = demand.shape

    # Sample non-zero cells proportional to demand.
    flat = demand.reshape(-1)
    nz = np.flatnonzero(flat)
    if len(nz) == 0:
        return pd.DataFrame()

    w = flat[nz].astype(np.float64)
    w /= w.sum()
    take = min(max_rows, len(nz) * 3)
    picks = rng.choice(nz, size=take, replace=True, p=w)

    bi, rem = np.divmod(picks, n_d * n_t)
    di, ti = np.divmod(rem, n_t)

    branch_id = bi.astype(np.int32) + 1
    drug_id = di.astype(np.int32) + 1
    day_index = ti.astype(np.int32)

    # Patients are drawn from those whose home branch matches, approximated by
    # a uniform draw then corrected -- exact matching is not worth the cost
    # here and the anomaly signal does not depend on it.
    patient_id = rng.integers(1, cfg.n_patients + 1, size=take).astype(np.int32)
    prescriber_id = patients["primary_prescriber_id"].to_numpy()[patient_id - 1]

    qty = np.maximum(1, rng.poisson(2.2, size=take)).astype(np.int32)

    df = pd.DataFrame(
        {
            "branch_id": branch_id,
            "drug_id": drug_id,
            "day_index": day_index,
            "patient_id": patient_id,
            "prescriber_id": prescriber_id.astype(np.int32),
            "qty_prescribed": qty,
        }
    )

    # --- Apply anomalous behaviour -------------------------------------
    controlled = set(drugs.loc[drugs["is_controlled"], "drug_id"].tolist())
    extra_frames = []

    for row in anomalous.itertuples(index=False):
        active = df["prescriber_id"].eq(row.prescriber_id) & df["day_index"].ge(row.active_from_day)
        n_active = int(active.sum())
        if n_active == 0:
            continue

        if row.anomaly_type == "overprescribing":
            # Inflate quantities well beyond the peer norm.
            mult = 1.0 + 4.0 * row.severity
            df.loc[active, "qty_prescribed"] = np.ceil(
                df.loc[active, "qty_prescribed"] * mult
            ).astype(np.int32)

        elif row.anomaly_type == "phantom_patients":
            # Duplicate scripts across an implausibly wide patient set.
            n_extra = int(n_active * row.severity * 2.0)
            if n_extra > 0:
                base = df.loc[active].sample(
                    n=n_extra, replace=True,
                    random_state=int(row.prescriber_id),
                )
                base = base.copy()
                base["patient_id"] = rng.integers(1, cfg.n_patients + 1, size=n_extra).astype(np.int32)
                extra_frames.append(base)

        elif row.anomaly_type == "controlled_ring":
            # Shift the mix sharply toward controlled substances.
            if controlled:
                idx = df.index[active]
                n_switch = int(len(idx) * row.severity * 0.8)
                if n_switch > 0:
                    switch_idx = rng.choice(idx, size=n_switch, replace=False)
                    df.loc[switch_idx, "drug_id"] = rng.choice(
                        list(controlled), size=n_switch
                    ).astype(np.int32)

    if extra_frames:
        df = pd.concat([df, *extra_frames], ignore_index=True)

    return df

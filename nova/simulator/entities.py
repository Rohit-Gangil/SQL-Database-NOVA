"""Entity generation: companies, branches, drugs, prescribers, patients.

Drug categories carry a seasonal phase drawn from real epidemiology (respiratory
infections peak in winter, antihistamines in spring pollen season), so the
seasonality a model recovers is not an arbitrary sine wave.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nova.config import SimConfig

# (category, annual peak day-of-year, seasonal amplitude, criticality, controlled)
#
# Peak day-of-year is where demand is highest. Amplitude 0 means aseasonal --
# chronic-disease medication does not care what month it is, and a model that
# imposes seasonality on it will do worse than one that does not.
DRUG_CATEGORIES: list[tuple[str, int, float, int, bool]] = [
    ("antibiotic",       15,  0.45, 4, False),  # winter respiratory infections
    ("antihistamine",   105,  0.55, 2, False),  # spring pollen
    ("antipyretic",      20,  0.40, 3, False),
    ("antimalarial",    220,  0.50, 4, False),  # monsoon
    ("cardiovascular",  180,  0.05, 5, False),  # chronic: near-aseasonal
    ("antidiabetic",    180,  0.04, 5, False),  # chronic
    ("analgesic",       180,  0.12, 2, False),
    ("opioid",          180,  0.08, 5, True),   # controlled
    ("psychiatric",     330,  0.18, 4, True),   # mild winter uptick
    ("dermatological",  150,  0.30, 1, False),
    ("gastrointestinal", 60,  0.20, 3, False),
    ("vitamin",          10,  0.25, 1, False),
]

REGIONS = ["North", "South", "East", "West", "Central"]
DOSAGE_FORMS = ["tablet", "capsule", "syrup", "injection", "ointment"]
SPECIALTIES = [
    "General Medicine", "Cardiology", "Endocrinology", "Pulmonology",
    "Psychiatry", "Dermatology", "Orthopaedics", "Paediatrics",
    "Gastroenterology", "Neurology",
]


def make_companies(cfg: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    names = [
        "Cipla", "Sun Pharma", "Dr Reddy's", "Lupin", "Zydus", "Torrent",
        "Glenmark", "Alkem", "Mankind", "Aurobindo", "Pfizer India", "GSK India",
    ][: cfg.n_companies]
    return pd.DataFrame(
        {
            "company_id": np.arange(1, len(names) + 1, dtype=np.int32),
            "name": names,
            # Reliability drives supply-shock probability: some manufacturers
            # are simply more likely to go offline.
            "reliability": rng.beta(8, 2, size=len(names)).round(3),
        }
    )


def make_branches(cfg: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    ids = np.arange(1, cfg.n_branches + 1, dtype=np.int32)
    regions = rng.choice(REGIONS, size=cfg.n_branches)
    # Branch scale is lognormal: a few large flagship stores, a long tail of
    # small ones. This is what makes the forecasting hierarchy non-trivial --
    # aggregating equal-sized branches would hide the reconciliation problem.
    scale = np.exp(rng.normal(0.0, 0.55, size=cfg.n_branches)).round(3)
    return pd.DataFrame(
        {
            "branch_id": ids,
            "code": [f"NOVA-{i:03d}" for i in ids],
            "name": [f"NOVA {r} {i}" for r, i in zip(regions, ids)],
            "region": regions,
            "city": [f"City{i % 14:02d}" for i in ids],
            "scale": scale,
            # Weekend traffic multiplier differs by branch: a hospital-adjacent
            # store behaves differently from a residential one.
            "weekend_factor": rng.uniform(0.55, 1.15, size=cfg.n_branches).round(3),
        }
    )


def make_drugs(cfg: SimConfig, rng: np.random.Generator,
               companies: pd.DataFrame) -> pd.DataFrame:
    n = cfg.n_drugs
    cat_idx = rng.integers(0, len(DRUG_CATEGORIES), size=n)
    cats = [DRUG_CATEGORIES[i] for i in cat_idx]

    unit_cost = np.round(np.exp(rng.normal(3.2, 0.9, size=n)), 2)
    margin = rng.uniform(1.18, 1.85, size=n)

    # Product lifecycle. ~12% of the catalogue launches mid-window and ~8% is
    # discontinued, so the panel is genuinely ragged: models must cope with
    # series that do not span the full horizon.
    launch_offset = np.where(
        rng.random(n) < 0.12,
        rng.integers(60, cfg.n_days // 2, size=n),
        0,
    )
    discontinue_offset = np.where(
        rng.random(n) < 0.08,
        rng.integers(cfg.n_days // 2, cfg.n_days, size=n),
        -1,
    )

    return pd.DataFrame(
        {
            "drug_id": np.arange(1, n + 1, dtype=np.int32),
            "trade_name": [f"{c[0][:4].title()}{i:03d}" for i, c in enumerate(cats, 1)],
            "company_id": rng.integers(1, len(companies) + 1, size=n).astype(np.int32),
            "category": [c[0] for c in cats],
            "season_peak_doy": np.array([c[1] for c in cats], dtype=np.int16),
            "season_amplitude": np.array([c[2] for c in cats], dtype=np.float32)
            * rng.uniform(0.7, 1.3, size=n).astype(np.float32),
            "criticality": np.array([c[3] for c in cats], dtype=np.int8),
            "is_controlled": np.array([c[4] for c in cats]),
            "dosage_form": rng.choice(DOSAGE_FORMS, size=n),
            "pack_size": rng.choice([1, 10, 15, 20, 30], size=n).astype(np.int16),
            "unit_cost": unit_cost,
            "sale_price": np.round(unit_cost * margin, 2),
            "shelf_life_days": rng.choice([180, 365, 540, 730, 1095], size=n).astype(np.int16),
            "launch_offset": launch_offset.astype(np.int16),
            "discontinue_offset": discontinue_offset.astype(np.int16),
            # Popularity shifts the demand rate for this drug across all
            # branches -- the drug-level main effect in the hierarchy.
            "popularity": np.exp(rng.normal(0.0, 0.85, size=n)).astype(np.float32),
        }
    )


def make_prescribers(cfg: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.n_prescribers
    return pd.DataFrame(
        {
            "prescriber_id": np.arange(1, n + 1, dtype=np.int32),
            "specialty": rng.choice(SPECIALTIES, size=n),
            "years_experience": rng.integers(1, 41, size=n).astype(np.int16),
            # Volume persona: how many prescriptions this prescriber writes.
            "volume_factor": np.exp(rng.normal(0.0, 0.6, size=n)).astype(np.float32),
        }
    )


def make_patients(cfg: SimConfig, rng: np.random.Generator,
                  branches: pd.DataFrame, prescribers: pd.DataFrame) -> pd.DataFrame:
    n = cfg.n_patients
    # Branch assignment weighted by branch scale: large branches serve more
    # patients.
    p = branches["scale"].to_numpy()
    p = p / p.sum()
    return pd.DataFrame(
        {
            "patient_id": np.arange(1, n + 1, dtype=np.int32),
            "birth_year": rng.integers(1935, 2019, size=n).astype(np.int16),
            "sex": rng.choice(["M", "F", "O"], size=n, p=[0.48, 0.50, 0.02]),
            "home_branch_id": rng.choice(branches["branch_id"], size=n, p=p).astype(np.int32),
            "primary_prescriber_id": rng.integers(
                1, len(prescribers) + 1, size=n
            ).astype(np.int32),
            # Baseline adherence propensity, used by the P8 intervention.
            "adherence_base": rng.beta(5, 3, size=n).astype(np.float32),
        }
    )

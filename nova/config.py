"""Central configuration for the NOVA pipeline.

Every stochastic component in this project reads its seed from here. A single
`SEED` makes the whole pipeline -- data generation, splits, model training --
reproducible from a cold start, which is a precondition for any reported number
being checkable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
ARTIFACT_DIR = REPO_ROOT / "artifacts"
# Named `warehouse.duckdb`, not `nova.duckdb`: DuckDB derives the catalog name
# from the filename, so `nova.duckdb` would create a catalog `nova` that
# collides with the `nova` schema and makes every qualified reference ambiguous.
DUCKDB_PATH = DATA_DIR / "warehouse.duckdb"

SEED = 20260727


@dataclass(frozen=True)
class SimConfig:
    """Parameters of the demand-generating process.

    Sizing note: 30 branches x 180 drugs x 1095 days = 5,913,000 series-days.
    Three full annual cycles is the minimum that lets a model learn annual
    seasonality from two and be evaluated on the third; two years would leave
    the backtest unable to distinguish a learned season from a fitted trend.
    """

    n_branches: int = 30
    n_drugs: int = 180
    n_companies: int = 12
    n_prescribers: int = 400
    n_patients: int = 12_000

    start_date: date = date(2023, 1, 1)
    end_date: date = date(2025, 12, 31)

    # --- Intermittency -------------------------------------------------
    # Demand rate per (branch, drug, day) is lognormal. These parameters are
    # chosen so the realised zero-cell fraction lands in [0.65, 0.90], which
    # is asserted as a test rather than assumed. Most SKUs at most branches
    # sell nothing on most days -- that is the defining property of pharmacy
    # demand and the reason naive time-series methods fail on it.
    log_rate_mean: float = -1.35
    log_rate_sd: float = 1.15

    # Negative-binomial dispersion for demand size given an occurrence.
    # >1 means variance exceeds the mean (overdispersion), which is what real
    # demand does and what a Poisson assumption gets wrong.
    size_dispersion: float = 1.6

    # --- Seasonality ---------------------------------------------------
    annual_amplitude_max: float = 0.55   # peak deviation for seasonal drugs
    weekly_amplitude: float = 0.22       # weekday/weekend branch traffic

    # --- Injected ground truth ----------------------------------------
    anomalous_prescriber_frac: float = 0.015
    n_supply_shocks: int = 18
    n_regime_changes: int = 10

    # --- Incumbent inventory policy -----------------------------------
    # The baseline NOVA must beat: a fixed reorder point set from a trailing
    # mean, with a flat safety factor applied identically to every SKU. This
    # is deliberately the policy most small chains actually run, not a straw
    # man -- it is reasonable, just not cost-optimal.
    incumbent_review_days: int = 7
    # Calibrated, not guessed. A sweep over the safety factor (recorded in
    # docs/SIMULATOR.md) was run and 3.0 selected because it lands the
    # incumbent at ~92% fill rate and ~1.5% expiry waste -- inside the bands
    # real pharmacy chains actually operate in. An earlier value of 1.5 gave
    # a 70% fill rate, which would have made every improvement NOVA reports
    # an artefact of a straw-man baseline.
    incumbent_safety_factor: float = 3.0
    default_lead_time_days: int = 3

    # --- Cost model ----------------------------------------------------
    # Holding cost as a fraction of unit cost per day (~18%/yr capital +
    # storage). Stockout penalty is a multiple of unit margin, scaled by the
    # drug's criticality: running out of a life-critical drug costs far more
    # than the lost margin, because the script transfers and the patient may
    # be harmed.
    holding_cost_rate_daily: float = 0.0005
    stockout_penalty_by_criticality: dict[int, float] = field(
        default_factory=lambda: {1: 1.0, 2: 1.8, 3: 3.0, 4: 6.0, 5: 12.0}
    )

    @property
    def n_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def n_series(self) -> int:
        return self.n_branches * self.n_drugs


@dataclass(frozen=True)
class SplitConfig:
    """Time-based splits. There is no random splitting anywhere in this repo.

    Series-days are ordered in time; a random split would let the model see
    Wednesday while predicting Tuesday, which inflates every metric and is the
    single most common way a portfolio forecasting project reports numbers it
    has not earned.
    """

    train_end: date = date(2025, 6, 30)
    # Rolling-origin backtest: each origin forecasts the next `horizon` days.
    backtest_origins: tuple[date, ...] = (
        date(2025, 7, 1),
        date(2025, 8, 1),
        date(2025, 9, 1),
        date(2025, 10, 1),
        date(2025, 11, 1),
        date(2025, 12, 1),
    )
    horizon_days: int = 14
    # Data-availability lag: yesterday's sales are not in the warehouse at
    # 00:00 today. Features must respect this or they are leaking.
    feature_lag_days: int = 1


SIM = SimConfig()
SPLIT = SplitConfig()

# The Demand-Generating Process

Every distribution and parameter used to build the dataset, so that any result in
this repository can be traced back to what actually generated it.

Run it with:

```bash
python -m nova.simulator.run          # full: 5,918,400 series-days
python -m nova.simulator.run --small  # reduced, for CI
```

## Why synthetic

Three reasons, in order of weight (also recorded as D-003):

1. **Real prescription data is PHI** and cannot live in a public repository.
2. **Known ground truth.** The simulator records which prescribers are anomalous,
   when supply shocks occurred, and what the true causal effect of the intervention
   is. Precision@k against a *known* answer is measurable; precision@k against
   guessed labels is theatre.
3. **Controllable stress.** Regime changes and supply outages can be injected at
   chosen times so that drift detection and error decomposition have something
   definite to find.

The corresponding limitation is stated plainly in the README: these results
demonstrate that the *methods* work on data whose generating process is known. They
are not evidence of real-world clinical or commercial performance.

## Shape

| | |
|---|---|
| Branches | 30, across 5 regions, lognormal size |
| Drugs | 180, across 12 therapeutic categories |
| Days | 1,095 (2023-01-01 → 2025-12-31) |
| **Series-days** | **5,918,400** |
| Prescription rows | ~1.2M attributed to prescriber/patient pairs |

Three full annual cycles is the minimum that lets a model learn annual seasonality
from two and be evaluated on a third. With two years, a backtest cannot distinguish
a learned season from a fitted trend.

## Demand

For branch *b*, drug *d*, day *t*:

```
mu[b,d,t] = lambda[b,d]
            x annual(t; peak_doy[d], amplitude[d])
            x weekly(t; weekend_factor[b])
            x lifecycle(t; launch[d], discontinue[d])
            x regime(t)
            x trend(t)

demand[b,d,t] ~ NegBinom(mean = mu, dispersion k = 1.6)
```

**Base rate.** `log lambda[b,d] ~ Normal(-1.35, 1.15)`, scaled by branch size and
drug popularity (both lognormal). The low median is what produces intermittency:
most cells are zero because their rate is genuinely tiny, not because zeros were
sprinkled on afterwards. **Realised zero-sales fraction: 74.4%** — asserted to lie
in [0.65, 0.90] by `test_zero_fraction_within_target_band`.

Under the Syntetos–Boylan classification (ADI ≥ 1.32, CV² ≥ 0.49), **94.0% of the
5,400 series are "lumpy"** and 6.0% "erratic" — the regime where classical
exponential smoothing fails outright, which is the whole reason the model ladder in
P6 starts with Croston rather than ETS.

**Why negative binomial and not Poisson.** Real demand is overdispersed: variance
exceeds the mean. A Poisson panel is smoother than reality and flatters every model
trained on it. `test_demand_is_overdispersed` asserts variance > mean on >90% of
active series.

**Annual seasonality** is a cosine peaking at a category-specific day of year, taken
from real epidemiology rather than chosen arbitrarily:

| Category | Peak | Amplitude | Rationale |
|---|---|---|---|
| antibiotic | day 15 | 0.45 | winter respiratory infections |
| antihistamine | day 105 | 0.55 | spring pollen |
| antimalarial | day 220 | 0.50 | monsoon |
| cardiovascular | day 180 | 0.05 | chronic — effectively aseasonal |
| antidiabetic | day 180 | 0.04 | chronic — effectively aseasonal |
| opioid *(controlled)* | day 180 | 0.08 | chronic |

The near-zero amplitudes matter as much as the large ones: a generator that smeared
one global season across the whole catalogue would be easier to forecast than
reality. `test_seasonal_amplitude_tracks_configuration` checks that *recovered*
amplitude correlates with *configured* amplitude across drugs (r > 0.6), which fails
if chronic medication comes back seasonal.

**Weekly seasonality** peaks Friday/Saturday, modulated per branch by its own
weekend factor — a hospital-adjacent store behaves unlike a residential one.

**Lifecycle.** ~12% of the catalogue launches mid-window (60-day ramp) and ~8% is
discontinued. The panel is therefore genuinely ragged; a model assuming every series
spans the full window mishandles roughly a fifth of the catalogue.

**Trend.** +12% chain-wide across three years.

## Inventory, and the censoring it creates

True demand is not what the business observes. The simulator runs the **incumbent
replenishment policy** day by day — periodic review (7 days), fixed reorder point
from a trailing 28-day mean, flat safety factor 1.5, lead time 3 days, orders rounded
up to pack size — and serves demand from real lots, first-expiry-first-out.

```
observed_sales = min(true_demand, stock_available)
unmet          = true_demand - observed_sales
```

**This is the point of the whole module.** A model trained on observed sales learns
that a stockout day had low demand; that drives the next forecast down, which causes
the next stockout. This is **demand censoring**, and it is why forecasting systems
built naively on sales data quietly degrade. P5 corrects for it; the simulator
creates it faithfully so there is something real to correct.

Critically, **the incumbent reviews its own sales, not true demand**, because it has
no way to see demand it failed to serve. That is exactly how a fixed-ROP policy
spirals on a fast-moving SKU.

### Calibrating the baseline so it is not a straw man

The safety factor was **swept, not guessed**. Beating an incompetent baseline proves
nothing, so it was tuned until the incumbent operated where real pharmacy chains
operate — 92–96% fill rate, 2–3% expiry waste:

| Safety factor | Fill rate | Expiry waste | Series-days with unmet |
|---:|---:|---:|---:|
| 1.5 | 76.6% | 1.79% | 5.55% |
| 2.0 | 83.6% | 1.66% | 4.15% |
| 2.5 | 88.9% | 1.56% | 2.96% |
| **3.0 (selected)** | **92.3%** | **1.51%** | **2.19%** |
| 4.0 | 96.2% | 1.47% | 1.21% |

Two defects were found and fixed during this calibration, both of which had been
quietly flattering the setup:

1. **Opening stock was destroyed on the first delivery.** Initial inventory was
   seeded into cohort slot 0, which is also where the first arrival (day `lead`)
   lands — and the receipt path overwrites a slot rather than adding to it. The
   opening stock was silently written off as expiry waste. This made the
   fill-rate/safety-factor curve non-monotonic.
2. **Stock arrived with full shelf life.** Real distributors ship with 40–80%
   of nominal shelf life already consumed. Modelling receipt as fresh understated
   expiry waste by more than an order of magnitude (0.08% against an industry norm
   of 2–3%), which made the over-stock arm of the newsvendor trade-off effectively
   free and the optimisation half-trivial.

**Realised at the selected setting: 1.60% of series-days carry unmet demand, 92%
fill rate.**

## Ground truth (schema `nova_truth`)

Held in a **separate schema** that no feature query touches. The separation is
physical rather than by convention, because the failure mode — a label leaking into
a feature and producing a meaningless 0.99 AUC — is silent.

| Table | Contents |
|---|---|
| `demand_true` | True demand and `mu`, the irreducible-error floor |
| `anomalous_prescriber` | 1.5% of prescribers: overprescribing, phantom patients, controlled rings; severity spread 0.35–1.0 |
| `supply_shock` | 18 manufacturer outages, 14–30 days, weighted toward unreliable makers |
| `regime_change` | 10 demand shifts in the final third, bimodal (collapse or surge) |

`mu` deserves emphasis: it is the conditional mean of the generating process, so no
forecaster can beat it. Reporting model error against that floor is more honest than
reporting it against zero, and it is what lets P6 say how much of the remaining error
is *reducible*.

Severity of injected anomalies is deliberately spread across a wide range. A detector
that only finds blatant cases should score well at k=10 and poorly at k=100 — and the
evaluation should show that rather than hide it.

## Reproducibility

Everything derives from `nova.config.SEED = 20260727`. `test_identical_seed_gives_identical_data`
asserts two runs are bit-identical; `test_different_seed_gives_different_data` guards
against a seed being silently ignored.

## Known limitations

- **No cross-SKU substitution in demand.** When a drug stocks out, that demand is
  recorded as unmet rather than partly flowing to a generic substitute. Real
  substitution would dampen the measured cost of stockouts, so the reported savings
  are, if anything, optimistic on this axis. Substitution is modelled in the schema
  (`dispense.substituted_drug_id`) but not exercised by the generator.
- **Patient-branch assignment is approximate** in the prescription sample; the
  anomaly signal does not depend on it, but branch-level patient analytics would.
- **No price elasticity.** Price history exists in the schema and is not yet a demand
  driver.
- **Lead time is deterministic** at 3 days. Real lead times are stochastic, and that
  variance is a major driver of required safety stock — so the simulated environment
  is somewhat easier than reality.

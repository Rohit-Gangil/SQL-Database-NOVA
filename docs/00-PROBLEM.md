# Phase 0 — Problem Definition

> **One sentence:** NOVA predicts, for every drug at every pharmacy branch, how much
> demand is coming and how much to reorder — so branches stop running out of drugs
> patients need, and stop throwing away drugs that expire on the shelf.

---

## 1. The problem, precisely

A multi-branch pharmacy chain must decide, for each `(branch, drug, day)` triple,
how many units to hold. Two failure modes sit on either side of that decision:

| Failure | Mechanism | Who pays |
|---|---|---|
| **Stockout** | Order too little | Patient leaves without medication; script transfers to a competitor; clinical harm for chronic/acute drugs |
| **Expiry waste** | Order too much | Pharmacy eats the cost of destroyed inventory; working capital tied up |

These pull in opposite directions, so this is not a "predict the number" problem —
it is an **asymmetric-cost decision problem under uncertainty.** The cost of being
one unit short is not the cost of being one unit long, and the ratio differs per drug.

What makes it genuinely hard, rather than a regression exercise:

1. **Demand is intermittent.** Most `(branch, drug, day)` cells are zero. A typical
   branch stocks thousands of SKUs but sells only a handful of each per week.
   Intermittent demand is "random demand with a large proportion of zero values" and
   defeats standard time-series methods, which is why Croston (1972) split the problem
   into forecasting *demand size* and *inter-demand interval* separately.
2. **Demand is hierarchical.** SKU → branch → region → national forecasts must
   reconcile — they have to sum. Independent per-series models do not.
3. **Perishability.** Unlike general retail, over-ordering does not just cost carrying
   charges; stock expires and is destroyed outright.
4. **Regulated substitution.** A stockout is sometimes absorbable by a generic
   substitute and sometimes not — the cost of error is drug-dependent.

## 2. Evidence that real companies pay to solve this

**Shortages and stockouts are large, persistent, and expensive.**
As of April 2025 there were ~270 active drug shortages in the US, with ~1,481
cumulative shortages over the prior decade. More than 40% of active shortages began
in 2022 or earlier; most last around 18 months and half extend beyond two years.
A Vizient survey found US hospitals spent roughly 20 million labor hours in 2023
managing drug shortages — **~$900M annually in labor cost alone**, more than double
the ~$360M reported in 2019. 43% of respondents reported medication errors connected
to shortages, and 27% reported disruptions to patient care.

**Waste on the other side of the decision is comparably large.**
Industry-average drug expiration waste runs **2–3% of inventory value**, with
overstocking, poor tracking and expiry together cited as high as 15–25% of annual
inventory value. For a pharmacy operation with a $10M annual drug budget, a 2–7%
waste rate is **$200k–$700k of avoidable loss per year.**

**Adherence — the downstream consequence of a patient not getting their drug — is
one of the largest addressable costs in US healthcare.** Estimates of the annual cost
of medication non-adherence range from ~$100B in direct costs to $290B+ including
avoidable spending. Non-adherence is associated with ~125,000 deaths annually and at
least 10% of hospitalizations; roughly 50% of patients do not take medications as
prescribed.

**Who is actively building this:** Amazon Pharmacy and Amazon's SCOT (Supply Chain
Optimization Technologies) org, CVS and Walgreens inventory/adherence programs, PBMs
running fraud-waste-abuse detection, and Indian chains (Tata 1mg, PharmEasy, Apollo)
doing demand planning across thousands of branches. Academic and industry work on
this exact problem is active and current — temporal-hierarchy forecasting for hospital
pharmacies, hierarchical Bayesian TSB models for heterogeneous intermittent demand,
and probabilistic intermittent-demand forecast combination.

**Sources**
- [Vizient: drug shortages cost hospitals ~$900M annually in labor](https://secure.businesswire.com/news/home/20250610263164/en/New-Vizient-Survey-Finds-Drug-Shortages-Cost-Hospitals-Nearly-%24900M-Annually-in-Labor-Expenses)
- [Vizient: Beyond the shortage — hidden cost of supply chain disruptions](https://vizientinc-delivery.sitecorecontenthub.cloud/api/public/content/0fed86e17e654732ba642464400e713f)
- [Drug shortage update Q3 2025 — VytlOne](https://vytlone.com/blog/drug-shortage-update-q3-2025/)
- [Pharmaceutical Commerce: why inventory economics determine patient access](https://www.pharmaceuticalcommerce.com/view/why-inventory-economics-determine-patient-access)
- [Bluesight: the real cost of pharmaceutical waste](https://bluesight.com/news/the-real-cost-of-pharmaceutical-waste/)
- [Expired drugs cost pharmacy departments plenty — Indispensable Health](https://www.indispensablehealth.com/blog/expired-drugs-cost-pharmacies)
- [Pharmacy Times: does nonadherence really cost $300B annually?](https://www.pharmacytimes.com/view/does-nonadherence-really-cost-the-health-care-system-300-billion-annually)
- [Medication adherence: helping patients take their medicines as directed (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3234383/)
- [Drug demand forecasting for hospital pharmacies using temporal hierarchies](https://www.tandfonline.com/doi/full/10.1080/01605682.2026.2620515)
- [Forecasting intermittent demand for inventory management by retailers (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0969698921002289)
- [Taxonomy-conditioned hierarchical Bayesian TSB models (arXiv 2511.12749)](https://arxiv.org/pdf/2511.12749)
- [Combining probabilistic forecasts of intermittent demand (arXiv 2304.03092)](https://arxiv.org/pdf/2304.03092)

## 3. The customer and the decision improved

**Customer:** the inventory planner / pharmacy operations lead at a multi-branch chain.

**Decision improved:** the nightly replenishment order — *for each branch and drug,
how many units to order today.* Today this is typically a fixed reorder point set by
rule of thumb (`reorder when below N`, `N` set once and rarely revisited). NOVA
replaces the fixed rule with a **per-SKU probabilistic forecast fed into a
cost-optimal order quantity.**

The distinction that matters: the deliverable is **an order quantity, not a
prediction.** A forecast that is not converted into a decision has no measurable value.

## 4. Business metrics (the ones we will actually move)

| Metric | Definition | Direction |
|---|---|---|
| **Service level** | % of demand-days where requested units were in stock | ↑ |
| **Stockout rate** | % of `(branch, drug, day)` cells with unmet demand | ↓ |
| **Expiry waste** | units destroyed / units purchased | ↓ |
| **Holding cost** | average capital tied up in inventory | ↓ |
| **Total cost** | `stockout_penalty + holding_cost + waste_cost`, in ₹ | ↓ *(primary)* |

**Total cost is the primary metric.** Accuracy metrics (WAPE, RMSSE, pinball loss)
are reported as diagnostics, but the headline claim must be in currency, because a
forecast improvement that does not reduce cost is not an improvement.

Secondary/model metrics: WAPE and RMSSE for point forecasts, pinball loss and
calibration coverage for probabilistic forecasts, precision@k for anomaly detection.

## 5. Non-goals

- **Not a clinical decision support system.** NOVA never recommends a therapy,
  a dose, or a substitution to a clinician. It forecasts units and orders stock.
- **Not real patient data.** All data is synthetic (see Phase 3). No PHI ever enters
  this repo. Public reference vocabularies only.
- **Not a pharmacy POS/ERP.** We model the replenishment decision, not billing,
  insurance adjudication, or dispensing workflow.
- **Not a drug-discovery or molecular-property project.** Chemistry appears only as
  SKU metadata.
- **No claim of clinical validity.** Results are demonstrated on a simulator with
  known ground truth; that is a strength for evaluation and a limitation for
  real-world generalization, and will be stated as such.

## 6. Theme decision: **KEEP the domain, SHARPEN the framing**

**Decision: no re-theme.**

**Justification.** The re-theme test was: is another domain *materially* stronger AND
able to reuse the existing relational schema? No. The existing schema already carries
the four entities the flagship problem needs — `Pharmacy` (branch), `Drugs` (SKU),
`Pharmacy_Sells` (price/assortment), `Drugs_Prescribed` (demand signal) — and the
domain maps to a problem that is demonstrably funded at Amazon, CVS, Walgreens and
every large pharmacy chain. A re-theme would cost roughly a week and buy nothing.

**What does change — the framing.** The project stops being *"a database of a
pharmacy"* and becomes *"a decision system for pharmacy replenishment."* Concretely:

| | Before | After |
|---|---|---|
| Unit of value | A table that stores data | An order quantity that saves money |
| Center of gravity | 24 CRUD procedures | Forecast → decision → measured ₹ |
| `Stock` table | 1 unusable row per branch | Per-branch-per-drug inventory ledger over time |
| Data | 14 hand-typed rows | 5M+ simulated rows with seasonality and known ground truth |
| Success | "The queries run" | "Total cost fell X% vs. the incumbent policy" |

The old CRUD layer is not deleted. It is **demoted to Layer 0** — the OLTP
source-of-truth the analytics stack reads from — which is exactly the role it plays
in a real company, and a more honest architecture than most portfolio ML projects
that begin at `train.csv`.

## 7. What "done" looks like

A reviewer clones the repo, runs `docker compose up` and one `make` target, and sees:
a reproducible simulated dataset, a table of forecasting baselines with error bars
where each row is beaten by the next, and a final line stating how much the optimized
policy reduces total cost against the incumbent fixed-reorder-point rule — with every
number regenerable from the repo.

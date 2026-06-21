# True Classic Paid Media Decision Engine — Project Report

> **What this is.** A reviewer-ready, end-to-end explanation of the True Classic
> Paid Media Decision Engine prototype: the business problem, what was built,
> how the numbers are produced, and where the honest boundaries are.
>
> **Read this first (the honest boundary).** Every dataset in this prototype is
> **deterministic synthetic data**, clearly labelled as such. The pipeline,
> models, optimizer, approval flow, and audit ledger are **real code**; the
> **data** and the **execution calls** are **synthetic / stubbed**. We do **not**
> claim causal identification, real-world accuracy, or production calibration.
> The LLM (planned Stage 5) makes **no** numeric or budget decisions — every
> forecast, constraint, allocation, approval check, payload, and audit record is
> computed by deterministic Python services. Latent generator "truth" (true
> marginal ROAS / incrementality) is used **only** for offline evaluation and is
> never exposed as normal product behaviour.
>

---

## Table of contents

1. [Executive Summary](#1-executive-summary)
2. [Brief Requirements and How the Prototype Satisfies Them](#2-brief-requirements-and-how-the-prototype-satisfies-them)
3. [Product Walkthrough](#3-product-walkthrough)
4. [Data Model and Ingestion](#4-data-model-and-ingestion)
5. [SKU Reconciliation and Attribution Calibration](#5-sku-reconciliation-and-attribution-calibration)
6. [Forecasting Engine](#6-forecasting-engine)
7. [Spend-Response and Diminishing Returns](#7-spend-response-and-diminishing-returns)
8. [Contribution Economics](#8-contribution-economics)
9. [Optimization and Constraints](#9-optimization-and-constraints)
10. [The Three Success Criteria](#10-the-three-success-criteria)
11. [Buyer & Inventory Handoff](#11-buyer--inventory-handoff)
12. [Approval, Execution, and Audit](#12-approval-execution-and-audit)
13. [Model Evidence and Technical Q&A Surface](#13-model-evidence-and-technical-qa-surface)
14. [Architecture](#14-architecture)
15. [AI-Assisted Development Workflow](#15-ai-assisted-development-workflow)
16. [Testing, Validation, and Reproducibility](#16-testing-validation-and-reproducibility)
17. [Limitations](#17-limitations)
18. [Future Work / Production Roadmap](#18-future-work--production-roadmap)
19. [Appendix](#19-appendix)

---

## 1. Executive Summary

### What it does, in one paragraph

The True Classic Paid Media Decision Engine is a vendor-neutral **decision and
governance layer** that sits over fragmented Meta + Google advertising data and
Shopify commerce truth. It ingests platform-shaped exports, reconciles them into
one canonical model, forecasts each campaign's next-7-day revenue, estimates how
revenue responds to *the next dollar* of spend, and then runs a constrained
optimizer that **reallocates budget to maximise net contribution after ad spend**
— subject to a blended-ROAS floor, an NC-CPA ceiling, a prospecting-share floor,
per-campaign movement bounds, and inventory no-scale guards. A marketer reviews
the plan, approves or rejects it, and the decision is written to a durable,
tamper-evident audit ledger. Execution payloads are generated but **stubbed** (no
live platform writes).

### The business decision it supports

> *Optimise risk-adjusted net contribution **at the margin**, not average ROAS.*
> A 6× historical channel may be saturated; a 4× channel may have profitable room
> to grow. The right budget move depends on the **next dollar's** expected return,
> under hard business and inventory guardrails.
> (Thesis: [README.md](README.md), [docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §0, §3.)

### The final recommendation outcome

The committed scenario (`SCN-e34a94f8174ffc70`, recommendation `REC-OPT-0001`,
engine `stage3.5`, **realistic** profile) reallocates a **fixed** daily budget of
**$138,405** across 7 campaigns (growth mode, $0 reserve) and is **feasible**, with
the SLSQP solver reporting *"Optimization terminated successfully."*
(Source: [reports/marts/mart_decision.csv](reports/marts/mart_decision.csv),
[reports/marts/mart_decision_line.csv](reports/marts/mart_decision_line.csv).)

### Key numbers (all traceable to artifacts)

| Metric | Current | Recommended | Source |
|---|--:|--:|---|
| Daily ad spend (fixed, growth mode) | $138,405 | $138,405 | `metrics.json` `decision.total_recommended_spend`; `mart_binding_constraint.csv` |
| **CM ROAS** (contribution $ per ad $; primary) | **1.82×** | **1.94×** | `metrics.json` `decision.cm_roas_current/projected` (1.8163 → 1.9406) |
| **Net contribution after ad spend** / day | **$112,980** | **$130,180** | `metrics.json` `decision.net_contribution_current/projected` |
| Contribution lift | — | **+$17,200 (≈ +15.2%)** | derived; [reports/economics/ECONOMICS.md](reports/economics/ECONOMICS.md) ("+$17,201, +15.2%") |
| Calibrated **blended ROAS** (the enforced 4.0× governance lens) | 3.93× | **4.19×** | `ECONOMICS.md` (3.93→4.19); `metrics.json` `blended_roas_projected` 4.1929 |
| NC-CPA (projected) | — | **$5.51** vs **$45** target (slack) | `mart_binding_constraint.csv` |
| Prospecting share | — | **30.04%** vs **30.00%** floor (binds) | `metrics.json` `decision.prospecting_share`; `REPORT.md` §10 |
| Inventory / buyer constraint | — | `TC-JOG-BLK` stockout risk pins **GOOGLE_PMAX** at current spend (no-scale) | `REPORT.md`; `economics.py`; inventory snapshot |

Notes on precision and provenance:

- **Calibrated blended ROAS** is the enforced 4.0× governance floor lens (gross
  calibrated/incremental revenue ÷ spend); **CM ROAS** and **net contribution**
  are the contribution-economics view (the optimizer's actual objective). They
  are different lenses on the same plan and are reported separately throughout.
- Older docs quote different ROAS deltas because they describe different dataset
  profiles / engine vintages (e.g. [README.md](README.md) `3.76 → 4.06`,
  [docs/AI_WORKFLOW.md](docs/AI_WORKFLOW.md) golden `≈3.88 → 4.12`). **This report
  treats the regenerated `realistic`-profile artifacts (engine `stage3.5`,
  `reports/model_performance/metrics.json` + `reports/economics/ECONOMICS.md`) as
  canonical** — i.e. `3.93 → 4.19` calibrated blended, `1.82 → 1.94` CM ROAS. The
  golden profile is the smooth regression benchmark the test suite pins to; the
  realistic profile is what the engine, API, and reports actually run on
  (D-034 / D-035).

### Data realism caveat

All figures above are produced from **realistic deterministic synthetic data**
(`data/realistic/`, seed `20240117`). They validate the modeling and decision
*machinery*; they are **not** real True Classic performance and imply **no causal
identification** ([reports/model_performance/REPORT.md](reports/model_performance/REPORT.md) header).

---

## 2. Brief Requirements and How the Prototype Satisfies Them

The exercise brief (`TrueClassic_AIExercise_PaidMedia_v2.docx`) asks for a
cross-platform paid-media decision tool with ingestion/unification, forecasting
with confidence and named models, spend-response/diminishing returns, constrained
budget reallocation with editable constraints and human approval, stubbed
execution, an audit trail, and a buyer/inventory handoff. The mapping below uses
the locked plan in [docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) as the canonical
interpretation of the brief.

| # | Requirement | Implementation | Evidence / path | Status |
|---|---|---|---|---|
| 1 | Meta + Google ingestion (API-shaped) | Adapters flatten Meta `data/paging` and Google nested `results` envelopes into the canonical model | [`ingestion/adapters.py`](backend/decision_engine/ingestion/adapters.py), [`ingestion/pipeline.py`](backend/decision_engine/ingestion/pipeline.py) | Done |
| 2 | SKU reconciliation | Deterministic fuzzy match → `auto_matched` / `needs_approval` / `quarantined`, human approves | [`ingestion/sku_resolution.py`](backend/decision_engine/ingestion/sku_resolution.py); `POST /api/sku-resolution/{id}/approve` | Done |
| 3 | Missing / quarantined / imputed records | 8 data-quality issue types detected from the feeds (dupes, missing dates, micros, null new-customer, immature labels, attribution mismatch, platform>Shopify, coverage gaps) | [`ingestion/quality.py`](backend/decision_engine/ingestion/quality.py); `IngestionSummary.dq_issues[]` | Done |
| 4 | Forecast for chosen SKU/campaign set | XGBoost quantile BAU forecast of 7-day-forward calibrated revenue, P10/P50/P90, per campaign | [`engine/bau_forecast.py`](backend/decision_engine/engine/bau_forecast.py) | Done |
| 5 | Named models + baselines | `xgboost_quantile`, `baseline_trailing_14d`, `baseline_same_weekday`, with a frozen champion selector | [`engine/selection.py`](backend/decision_engine/engine/selection.py), [`engine/baselines.py`](backend/decision_engine/engine/baselines.py) | Done |
| 6 | Confidence intervals / accuracy metrics | Conformalized (CQR) 80% band + WAPE/MAE/bias/coverage; deployed mixed-policy band | [`engine/intervals.py`](backend/decision_engine/engine/intervals.py); `REPORT.md` §3–4; `/api/model-evidence` | Done |
| 7 | Spend-response / diminishing returns | Orthogonalized (double-ML) residualized adstock response → marginal ROAS curve per campaign | [`engine/response.py`](backend/decision_engine/engine/response.py) | Done |
| 8 | Budget reallocation | SciPy SLSQP optimizer maximising net contribution after spend | [`engine/optimizer.py`](backend/decision_engine/engine/optimizer.py) | Done |
| 9 | Editable constraints | ROAS floor / NC-CPA / prospecting share / movement / reserve mode are query params, re-solve ≈ 10 ms | `GET /api/recommendation`; Budget Planner tab | Done |
| 10 | Marketer approval / reject | Idempotent terminal decision bound to an immutable snapshot by id; infeasible/superseded/stale/sensitivity plans cannot be approved | `POST /api/recommendation/{id}/decision`; [`api/store.py`](backend/api/store.py) | Done |
| 11 | Stub execution payloads | Approve emits stubbed Meta/Google set-budget payloads (`is_stub=true`); no live writes | `GET /api/recommendation/{id}/execution-preview`; `ExecutionPanel.tsx` | Done (stubbed) |
| 12 | Audit trail | Durable, append-only, **hash-chained** SQLite ledger + `verify` endpoint + 4 Looker-ready marts | [`api/store.py`](backend/api/store.py), [`api/marts.py`](backend/api/marts.py); `GET /api/audit/verify` | Done |
| 13 | Buyer / inventory handoff | Read-only inventory snapshot → days-of-cover, stockout date, reorder qty, urgency, no-scale flag joined to campaigns | [`api/inventory_service.py`](backend/api/inventory_service.py); Buyer & Inventory tab | Done |

---

## 3. Product Walkthrough

The web client is a **Vite + React 19 + TypeScript** single-page app in
[`frontend/`](frontend/) (Tailwind v4, lucide-react). It is a
**read-and-govern client** over the FastAPI backend — all numbers come from the
API; the UI owns no business logic. (The plan originally specified Next.js
[docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §10; the Next.js shell was retired in
favour of this Vite SPA — see `docs/DECISIONS.md` D-043.)

Seven tabs (left sidebar, [`frontend/src/components/Sidebar.tsx`](frontend/src/components/Sidebar.tsx)):

### Decision Overview (`DecisionOverview.tsx`)
The marketer's home screen. A **ranked scorecard** shows the primary outcome (CM
ROAS, net contribution current vs projected), then **policy guardrails** (calibrated
blended ROAS vs the 4.0× floor, NC-CPA, prospecting share, reserve), then context
metrics. Below it, a current-vs-recommended bar per campaign with reason codes,
risk flags, and marginal-ROAS-vs-hurdle tooltips. Approve/reject lives here; the
**Execution Preview panel only appears after approval**. Backed by
`recommendation.kpis` and `recommendation.lines[]`
([docs/UI_INTEGRATION_MAP.md](docs/UI_INTEGRATION_MAP.md) §1).

### Data Unification (`DataUnification.tsx`)
Source-health cards per feed (`raw` / `normalized` / `quarantined`), the
data-quality issue ledger, and the SKU-resolution table with an **Approve**
action for the campaign whose platform product ID maps to a needs-approval
candidate. Backed by `GET /api/ingestion` and `POST /api/sku-resolution/{id}/approve`.

### Forecast & Response (`ForecastResponse.tsx`)
Per-campaign 7-day forecast curve with the **80% deployed band**
(`forecast_p10/p50/p90`), the response-curve shape (`response_slope`,
`response_quad`), and `marginal_roas` vs `marginal_roas_downside`. Channel selector
iterates Meta + Google campaigns only.

### Budget Planner (`BudgetPlanner.tsx`)
The editable-constraints surface: sliders for `roas_floor`, `nc_cpa_target`,
`prospecting_min_share`, `movement_bound`, and a `reserve_mode` toggle
(`growth` / `efficiency_first`), plus Expected vs Conservative policy. "Recalculate"
calls `GET /api/recommendation` and the plan re-solves in ≈ 10 ms (the expensive
forecast/response context is cached).

### Buyer & Inventory (`BuyerInventory.tsx`)
Read-only inventory handoff: per SKU, the linked campaigns, units on hand,
forecast daily demand, days of cover, estimated stockout date, suggested reorder
quantity, stockout risk, and the **inventory no-scale** flag. Backed by
`GET /api/inventory`.

### Model Evidence (`ModelEvidence.tsx`)
A curated, versioned, latent-truth-stripped view of the model report with a
**fresh/stale verdict** against the active recommendation. Shows champion-selection
evidence (pre-test fold wins, WAPE bars, promotion reason) and **interactive
forecast-accuracy charts** (a forecast-vs-actual fan and an actual-vs-predicted
scatter, coloured by band coverage) on the untouched test set. Backed by
`GET /api/model-evidence` (`model-evidence.v2`).

### Audit & Business Controls (`AuditControls.tsx`)
Scenario history (`GET /api/audit/log`), hash-chain integrity badge
(`GET /api/audit/verify`), the calibration registry table with the sensitivity
override, and decision/event log expansions (payload hash, execution events,
status).

### The live demo flow (matches [docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §14)

1. **Run ingestion** — show feed health and row counts.
2. **Meta + Google normalization** — the two different envelope shapes flattened into one canonical table.
3. **SKU reconciliation / quality flags** — approve one suggested SKU mapping; show one quarantined ID and the DQ ledger.
4. **7-day forecast and model trust** — XGBoost vs the two baselines, P10/P50/P90, walk-forward error and coverage.
5. **Spend-response / marginal CM ROAS curve** — saturation vs room-to-scale, in-support vs extrapolation.
6. **Edit constraints** — e.g. tighten NC-CPA, flip to efficiency-first to push budget into reserve.
7. **Recompute recommendation** — re-solve in ≈ 10 ms.
8. **Review success criteria** — the ranked scorecard.
9. **Buyer/inventory impact** — the joggers' stockout risk blocking PMax scale-up.
10. **Approve or reject** — infeasible/superseded/stale plans are blocked.
11. **Audit ledger + stub execution payload** — the hash-chained decision and the generated (stubbed) Meta/Google budget payloads.

---

## 4. Data Model and Ingestion

### Source data (all synthetic, API-envelope-shaped)

The generator writes three **raw** feeds shaped like the real platform APIs
([data/README.md](data/README.md)):

- **Meta-style ad export** — `data/raw/meta_insights.json`, a Meta Marketing API
  `data/paging` envelope; numeric fields are strings; conversions live in
  `actions` / `action_values`. Carries the planted duplicate-record defect.
- **Google Ads-style export** — `data/raw/google_ads.json`, nested `results` with
  `campaign` / `metrics` / `segments`; money in `cost_micros`; some rows omit
  `segments.date` (the missing-extraction-date defect).
- **Shopify / commerce truth** — `data/raw/shopify_commerce.json`, the DTC
  source-of-record daily revenue per SKU; some `new_customer_revenue` are null
  (planted null defect).
- **SKU inventory snapshot** — part of the canonical `fact_inventory_snapshot`
  table (units on hand, demand, days of cover, stockout risk).

### Canonical model (13 tables)

Adapters flatten the raw feeds into a unified, model-ready canonical model
(CSV + Parquet + a DuckDB copy + `manifest.json`). The 13 tables
([docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §12, [data/README.md](data/README.md)):
`fact_ad_performance`, `dim_campaign`, `dim_sku`, `sku_alias`,
`fact_commerce_truth`, `fact_inventory_snapshot`, `data_quality_issue`,
`calibration_registry`, `model_run`, `model_evaluation`, `recommendation`,
`approval`, `execution_event`. Contracts are enforced with **Pandera** (tabular)
and **Pydantic** (API envelopes).

### How the messy parts are handled (detected, not silently fixed)

`ingestion/quality.py` (`detect()`) surfaces **8 data-quality issue types** from
the feeds:

| Issue | Handling |
|---|---|
| `duplicate_meta_record` | Natural-key dedup so revenue is not double-counted |
| `missing_google_extraction_date` | Quarantined and **flagged, not imputed** (could be zero or a failed pull) |
| `google_cost_micros_normalization` | `cost_micros / 1_000_000` normalization, recorded |
| `null_new_customer_value` | Shopify null new-customer revenue surfaced |
| `immature_conversion_labels` | Rows whose 7-day labels have not matured are excluded from training |
| `platform_revenue_exceeds_shopify` | Platform > Shopify DTC discrepancy flagged |
| `inconsistent_date_coverage` | Coverage gaps surfaced per campaign |
| `attribution_window_mismatch` | Observed per-campaign attribution model compared to the canonical policy (`meta: 7d_click_1d_view`, `google: data_driven`) and surfaced — never silently normalized |

Schema-invalid records are **quarantined** rather than dropped, with a reason
string. (Two-level validation: envelope + record.)

### Row counts, splits, and determinism (realistic profile)

From [reports/model_performance/REPORT.md](reports/model_performance/REPORT.md) §2
and `metrics.json`:

- Range **2025-01-06 → 2025-08-03**, **210 days**, **7 campaigns**, horizon **7d**.
- Rows: **raw 1461 → panel 1460** (duplicates removed **1**, immature labels excluded **49**).
- Chronological splits with a **7-day leakage gap**: **Train 840** (t[0,119]) · **Val 252** (t[126,161]) · **Test 235** (t[168,203]). The test period is **never** used for model selection.

Determinism is anchored by `MASTER_SEED = 20240117` ([`config.py`](backend/decision_engine/config.py))
with child RNG streams derived via `SeedSequence` (the global numpy RNG is never
touched). Fingerprints pin the artifacts:

| Fingerprint | Value | Source |
|---|---|---|
| Panel / data | `9b5120157a274c2f…` | `metrics.json` `panel_data_fingerprint`; `mart_decision.csv` |
| Canonical tables | `7ebbdf0b9e835a47…` | `REPORT.md`; `MANIFEST.json` |
| Config | `62336454841dec3e` | `mart_decision.csv` `config_fingerprint` |
| Calibration (approved) | `ec6729d77443c890` | `mart_decision.csv` |
| Effective calibration | `a131ad4285ed497e` | `mart_decision.csv` |
| Evidence input (report staleness) | `8f984b5049c4a8ef` | `metrics.json` `evidence_input_fingerprint` |

### Two dataset profiles (D-034 / D-035)

Two deterministic profiles share the **same latent truth**: **`realistic`** is the
PRIMARY/default (volatility + staggered exogenous spend experiments; `data/realistic/`)
used by the engine, API, and reports; **`golden`** is the smooth known-truth
**regression benchmark** (`data/{raw,canonical}`) the test suite hard-pins to. Both
fingerprints are pinned; `make generate` writes both.

> **Latent-truth isolation.** The generator's known response process (true marginal
> ROAS, incrementality, noise) is **never** written to `data/canonical` or
> `data/raw`. It lives in memory for evaluation and is persisted only under
> `data/internal/latent/` behind an explicit `--write-latent-truth` flag, so no
> adapter or feature path can pick it up (target-leakage prevention).

---

## 5. SKU Reconciliation and Attribution Calibration

### SKU reconciliation

Platform product identifiers map to canonical SKUs via **deterministic** fuzzy
matching (`difflib.SequenceMatcher`, top-3 candidates) in
[`ingestion/sku_resolution.py`](backend/decision_engine/ingestion/sku_resolution.py),
producing three states:

- **`auto_matched`** — high confidence, used as-is.
- **`needs_approval`** — a human must approve; the schema only offers an
  `allowed_candidates` list (e.g. the planted `GG_TC-JOG-BLU → TC-JOG-BLK` at
  confidence ≈ 0.58). The schema **rejects any SKU not in the list**, so the
  resolver (and later the LLM) cannot invent a mapping.
- **`quarantined`** — an unknown ID (e.g. `FB_UNMAPPED_99X`, `sku_id=None`) held
  out of the model with candidate suggestions only.

Approval is a human action (`POST /api/sku-resolution/{id}/approve`).

### Attribution and incrementality calibration (three separate layers — never one "haircut")

Per [docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §7, measurement is split into three
distinct adjustments:

1. **Deduplication** — Shopify provides the observed DTC order/revenue source of
   record used for reconciliation.
2. **Attribution normalization** — incompatible windows/models per platform are
   surfaced, not blended away.
3. **Incrementality calibration registry** — each entry carries `coefficient` +
   `source` + `effective_start/end` + `confidence` + `scope` + an explicit
   `is_synthetic` flag ([`calibration/registry.py`](backend/decision_engine/calibration/registry.py),
   served at `GET /api/calibration/registry`).

The engine decides on **calibrated (incremental)** revenue — platform-reported
revenue is recovered by dividing by the segment coefficient and is shown as
**context only**. A live sensitivity lever lets a marketer override a coefficient
to stress the plan; such a scenario is marked `is_sensitivity_override` and **can
never be approved/executed** (it uses non-registry-approved coefficients) — a
formal calibration revision would instead be written to the registry as a new
version.

> **Honest caveat.** In this prototype the registry copies the scenario's *true*
> incrementality, so calibration *error* is itself synthetic. The sensitivity
> lever lets you stress it, but it is **not** measured lift; production calibration
> still requires geo/conversion-lift experiments ([README.md](README.md)).

---

## 6. Forecasting Engine

### Target and discipline

**Model A (BAU forecast)** predicts **7-day-forward calibrated revenue**
(`target_fwd7`) at the current operating point, per campaign, at **P10/P50/P90**
([`engine/bau_forecast.py`](backend/decision_engine/engine/bau_forecast.py)). It
uses **mature labels only**, **chronological** splits, and a **7-day gap** between
train and validation so overlapping future labels cannot leak
([REPORT.md](reports/model_performance/REPORT.md) §1: target window verified,
immature labels excluded, *test used for selection: False*).

### Model candidates (named)

- **`xgboost_quantile`** — XGBoost quantile regression (`objective="reg:quantileerror"`,
  `n_estimators=200`, `max_depth=3`, `learning_rate=0.05`, monotone constraints on
  `spend` and `adstock_spend`, `n_jobs=1`, `random_state=MASTER_SEED`), with a
  13-feature set (spend, adstock_spend, dow, trend, lags/rolling, Fourier 7 & 365).
- **`baseline_trailing_14d`** — mean of the last 14 days' calibrated revenue × 7.
- **`baseline_same_weekday`** — sum of the last 7 days' calibrated revenue.

### Champion selection (frozen, pre-test only)

A **single shared, frozen selector** ([`engine/selection.py`](backend/decision_engine/engine/selection.py))
is used by both the live engine and the eval report, so they can never disagree.
XGBoost is promoted over the better baseline **only if all** of:

1. pooled WAPE improvement ≥ **`MATERIAL_WAPE_IMPROVEMENT = 0.05`** (5%),
2. it wins a **majority of pre-test folds** (`fold_wins * 2 ≥ n_folds`, folds at
   t[112,126], [127,147], [148,161]),
3. it does not fail the bias guard (`MAX_BIAS_FRACTION = 0.15`).

The result is a **per-campaign deployed policy**, not one global model. On the
untouched test, the selected mix achieves **WAPE 0.11098** (MAE 60283.96, bias
5682.64, ≈ 88.9% intuitive gloss), beating XGBoost-pooled WAPE 0.133353
([REPORT.md](reports/model_performance/REPORT.md) §3).

| Campaign | Selected (reason) | XGB P50 WAPE | trail-14d | same-wkday |
|---|---|--:|--:|--:|
| GOOGLE_BRAND | `baseline_same_weekday` (fallback −29.0% < 5%) | 0.0646 | 0.0606 | 0.0714 |
| GOOGLE_NONBRAND | `xgboost` (promoted: beats trail-14d 31.3%, 3/3 folds) | 0.1030 | 0.1219 | 0.1037 |
| GOOGLE_PMAX | `xgboost` (promoted: beats same-wkday 14.3%, 2/3) | 0.2366 | 0.0732 | 0.1013 |
| GOOGLE_SHOPPING | `baseline_same_weekday` (fallback −61.1%) | 0.2615 | 0.0398 | 0.0519 |
| META_ADV_SHOPPING | `baseline_trailing_14d` (fallback −19.2%) | 0.1322 | 0.1072 | 0.1187 |
| META_PROSPECTING | `xgboost` (promoted: beats trail-14d 7.5%, 2/3) | 0.0787 | 0.0737 | 0.0839 |
| META_RETARGETING | `xgboost` (promoted: beats trail-14d 8.2%, 2/3) | 0.1171 | 0.0457 | 0.0624 |

(Selection reasons: `metrics.json` `forecast.per_campaign[].reason`; WAPEs: `REPORT.md` §3.)

### Intervals (display-only)

- **XGBoost conformal (CQR)** band ([`engine/intervals.py`](backend/decision_engine/engine/intervals.py),
  target coverage **0.80**): raw held-out coverage **0.3968 → calibrated 0.8056**
  (offset 0.08471, fit on 252 held-out rows); on test the XGBoost conformal band is
  slightly conservative at **86.0%**.
- **Deployed mixed-policy band** (what the engine actually serves): conformal for
  XGBoost champions, an operational **±20% heuristic** for baseline champions —
  empirical coverage **0.8766**, mean width ≈ 183,915 over 235 test rows.

> The band is **display-only**: the decision basis is the marginal-ROAS ordering +
> the ROAS floor, not the P10/P90 interval ([README.md](README.md), `REPORT.md` §11).

### Model Evidence caveats (drift, surfaced not flipped)

Two XGBoost champions regressed on the untouched test relative to a baseline and
are flagged as a **retraining signal, not flipped** (flipping would leak test into
the policy): **GOOGLE_PMAX** (champion WAPE 0.2366 vs best baseline 0.0732, 223.2%
worse) and **META_RETARGETING** (0.1171 vs 0.0457, 156.2% worse)
([REPORT.md](reports/model_performance/REPORT.md) §11).

---

## 7. Spend-Response and Diminishing Returns

**Model B** estimates how revenue responds to a *change* in spend
([`engine/response.py`](backend/decision_engine/engine/response.py)) using an
**orthogonalized (double-ML)** procedure:

1. Out-of-fold Ridge **control models** predict revenue and adstocked spend from
   non-media structure only (day-of-week, trend, Fourier 7 & 365) — so seasonal /
   promo demand is not credited to media.
2. A local quadratic of the revenue residual on the centered adstock-spend residual
   gives the **marginal ROAS** at the current operating point.
3. A **block bootstrap** (200 resamples, block 14) yields a **downside** marginal.

The curve **contributes only a delta**: `R(b) − R(b_current)`, which is **0 at
current spend** by construction, so Model A owns the revenue *level* and Model B
owns the *change* — the two cannot double-count
([docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §5; [README.md](README.md)).

### Marginal ROAS vs marginal CM ROAS, and the hurdles

- **Contribution break-even** is at **1.00×** CM ROAS (the next dollar pays for
  itself in contribution).
- The per-campaign **marginal CM hurdle** is a uniform **1.05×** (`HARD_FLOOR_SAFETY
  = 1.05`): each campaign's gross hurdle is `(1/margin) × 1.05`, so the marginal
  *contribution* return at the hurdle is `margin × (1/margin) × 1.05 = 1.05×` for
  every campaign ([reports/economics/CM_FLOOR_SWEEP.md](reports/economics/CM_FLOOR_SWEEP.md)).
- **Observed support and movement bounds**: recommendations are bounded to **±20%**
  per campaign per cycle, and each campaign reports its `observed_spend_range` and
  whether the move stays `movement_in_support`.

### Recovery vs latent truth (offline validation only)

Because the generator is known, the report scores estimated marginals against the
latent truth ([REPORT.md](reports/model_performance/REPORT.md) §8): **Spearman
0.9643**, Pearson 0.9049, **sign accuracy 0.857**, hurdle-class accuracy 0.857.
Per-campaign estimated vs latent marginal ROAS (from `metrics.json`
`response.per_campaign`):

| Campaign | Est. marginal | Downside | Latent (eval-only) | In support |
|---|--:|--:|--:|:--:|
| GOOGLE_NONBRAND | 5.33 | 4.89 | 4.92 | yes |
| GOOGLE_PMAX | 4.37 | 3.98 | 3.38 | yes |
| GOOGLE_SHOPPING | 4.25 | 3.45 | 2.95 | no |
| META_PROSPECTING | 2.86 | 2.48 | 2.48 | no |
| META_RETARGETING | 0.10 | −0.72 | 0.10 | yes |
| META_ADV_SHOPPING | 0.48 | −2.30 | 2.45 | yes |
| GOOGLE_BRAND | −1.38 | −2.95 | 0.14 | yes |

> **This is observational/local, not causal proof.** Residualization reduces but
> does not eliminate confounding; the latent column exists only because this is a
> known synthetic generator and is **never** part of normal product output
> ([REPORT.md](reports/model_performance/REPORT.md) header; `metrics.json` note).

---

## 8. Contribution Economics

Margins are **emergent** from an explicit variable-cost stack, not tuned
([reports/economics/ECONOMICS.md](reports/economics/ECONOMICS.md), D-040). The
specific payment-fee, return-handling, and COGS-recovery values are **synthetic
assumptions, not verified True Classic ledger figures.**

### Per-SKU cost waterfall ($/order)

| SKU | Price | COGS | Outbound | Pay fee | Exp. refund | Net COGS recov. | Return handling | Contribution | CM rate |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| TC-CREW-BLK | 30.00 | 8.50 | 4.00 | 0.90 | 3.60 | +0.82 | 0.96 | 12.86 | 42.9% |
| TC-POLO-CLS | 45.00 | 12.00 | 4.50 | 1.35 | 6.30 | +1.34 | 1.12 | 21.07 | 46.8% |
| TC-JOG-BLK | 65.00 | 19.00 | 5.50 | 1.95 | 11.70 | +2.74 | 1.44 | 28.15 | 43.3% |
| TC-CREW-6PK | 99.00 | 28.00 | 7.00 | 2.97 | 11.88 | +2.69 | 0.96 | 50.88 | 51.4% |

- Revenue-weighted portfolio CM **46.2%**; spend-weighted CM (optimizer) **46.4%**
  → **break-even ROAS 2.157×**, **hard scale floor 2.264×**.
- The hard scale floor is **derived, not magic**: `(1/margin) × HARD_FLOOR_SAFETY`
  ([`economics.py`](backend/decision_engine/economics.py)); only the 1.05 safety
  multiplier is a policy knob ([CLAUDE.md](CLAUDE.md)).

### Per-campaign break-even and marginal hurdle (rises as margin falls)

| Campaign | SKU | CM rate | break-even ROAS | marginal hurdle (×safety) |
|---|---|--:|--:|--:|
| META_PROSPECTING | TC-CREW-BLK | 42.9% | 2.334× | 2.450× |
| META_ADV_SHOPPING | TC-CREW-6PK | 51.4% | 1.946× | 2.043× |
| META_RETARGETING | TC-POLO-CLS | 46.8% | 2.135× | 2.242× |
| GOOGLE_BRAND | TC-CREW-BLK | 42.9% | 2.334× | 2.450× |
| GOOGLE_NONBRAND | TC-POLO-CLS | 46.8% | 2.135× | 2.242× |
| GOOGLE_PMAX | TC-JOG-BLK | 43.3% | 2.309× | 2.425× |
| GOOGLE_SHOPPING | TC-CREW-6PK | 51.4% | 1.946× | 2.043× |

### Current vs optimized contribution

Net contribution after ads = `Σ mᵢ·Rᵢ − Σ bᵢ` on calibrated/incremental revenue.
Both rows use the **same** post-D-040 margins, so the comparison isolates the
allocation, not the cost model.

| Allocation | Pre-ad contribution | Ad spend | Net contribution after ads | CM ROAS |
|---|--:|--:|--:|--:|
| Current | $251,385 | $138,405 | $112,980 | 1.82× |
| Optimized candidate | $268,585 | $138,405 | $130,180 | 1.94× |

Net-contribution improvement **≈ +$17,200 (+15.2%)** at equal-or-lower spend
(`ECONOMICS.md`: "+$17,201, +15.2%"). Reverse-logistics assumptions are the
weakest input; `ECONOMICS.md` includes a sensitivity grid showing portfolio CM
ranges ≈ 40.4%–48.1% across return-rate / recovery / handling assumptions.

---

## 9. Optimization and Constraints

### Objective

Maximise **net contribution after ad spend**
([`engine/optimizer.py`](backend/decision_engine/engine/optimizer.py)):

```
maximize   Σ [ R_i(b_i) · m_i − b_i ]
```

where `R_i(b_i)` is the local calibrated incremental revenue (BAU level + Model-B
delta) and `m_i` is the contribution-margin rate. (Implemented as minimizing
`neg_contribution`.) ROAS is a **constraint, not the objective** — maximising a
ratio yields pathological low-spend solutions ([docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §3, §6).

### Constraints

| Constraint | Form | Default |
|---|---|---|
| Blended calibrated ROAS floor | `Σ R_i − floor·Σ b_i ≥ 0` | **4.0×** (`BLENDED_ROAS_FLOOR`) |
| Prospecting min share | `(pros·b) − min·Σ b_i ≥ 0` | **0.30** realistic / 0.33 golden (`PROSPECTING_MIN_SHARE`) |
| NC-CPA ceiling (monitored guardrail) | prospecting-spend vs `target·Σ(nc_pd·b)` | **$45** (`NC_CPA_TARGET`) |
| Movement bounds (per campaign) | `[current·(1−mb), current·(1+mb)]` ∩ daily cap | **±20%** (`MOVEMENT_BOUND`) |
| Budget conservation / reserve | growth: `Σ b_i = budget`; efficiency-first: `Σ b_i ≤ budget` | growth |
| Inventory no-scale | `hi = min(hi, current_spend)` if `inventory_constrained` | per SKU |
| Below-hurdle no-increase | `hi = min(hi, current_spend)` if `marginal_now < marginal_floor` | per campaign |
| (Optional) portfolio CM floor | sweep/analysis only, default OFF | off |

### Solver approach (honest framing)

SciPy **SLSQP** (`maxiter=300`, `ftol=1e-6`) with a **multi-start** strategy
(current / lower / upper / midpoint / proportional + up to 3 perturbations) and a
near-best agreement check. A **pre-solve feasibility** pass produces an explicit
conflict report rather than ever emitting an invalid plan; an infeasible solve
falls back to the current allocation with the conflicts attached. The committed
scenario reports `solver_success=1`, message *"Optimization terminated
successfully"*, 40 iterations, and (from the binding report)
`solver_converged`, `business_feasible`, `local_optimality_converged`,
`solver_qualified` — i.e. a **solver-converged, locally-optimal feasible
candidate**, not a globally certified optimum ([mart_decision.csv](reports/marts/mart_decision.csv);
[ECONOMICS.md](reports/economics/ECONOMICS.md)).

### The final recommendation (current → recommended per campaign)

Daily budget is **conserved** at **$138,405** (growth mode, $0 reserve). Current
spend = the trailing-14d anchor (`metrics.json` `response.per_campaign[].current_spend`);
recommended = `mart_decision_line.csv`.

| Campaign | Current $ | Recommended $ | Δ% | Driver |
|---|--:|--:|--:|---|
| GOOGLE_NONBRAND | 27,758 | 33,310 | **+20.0%** | highest marginal (5.33) → scale to movement cap |
| META_PROSPECTING | 22,451 | 24,102 | +7.4% | productive top-of-funnel; prospecting floor |
| GOOGLE_SHOPPING | 13,842 | 15,600 | +12.7% | strong economics, **capped at daily cap** |
| GOOGLE_PMAX | 15,420 | 15,420 | **0.0%** | **held — inventory no-scale (TC-JOG-BLK)** |
| META_ADV_SHOPPING | 18,980 | 17,471 | −7.9% | low marginal contribution |
| META_RETARGETING | 26,098 | 21,417 | −17.9% | saturated (marginal ≈ 0.10) → pull back |
| GOOGLE_BRAND | 13,856 | 11,085 | −20.0% | negative marginal (−1.38) → cut to movement floor |

### Binding constraints and trade-offs

From [mart_binding_constraint.csv](reports/marts/mart_binding_constraint.csv):

- `budget_fully_deployed` — **binding** ($138,405 of $138,405, reserve $0).
- `prospecting_min_share` — **binding** (30.04% vs 30.00%, margin +0.04pp).
- `blended_roas_floor` — **slack** (4.193× vs 4.00×, margin +0.193×).
- `nc_cpa_target` — **slack** ($5.51 vs $45.00, margin +$39.49).

So the plan is held by the **budget conservation** and **prospecting floor**;
the ROAS floor and NC-CPA have comfortable headroom. The trade-off story: the
optimizer wants to pour more into GOOGLE_NONBRAND/SHOPPING, but **±20% movement**,
the **GOOGLE_SHOPPING daily cap**, and the **PMax inventory hold** prevent it, while
the prospecting floor keeps the top of funnel funded. A CM-floor policy sweep
([CM_FLOOR_SWEEP.md](reports/economics/CM_FLOOR_SWEEP.md)) shows that in growth mode
a portfolio CM floor is **redundant** with the objective (CM pinned at 1.94×) and
in efficiency-first it only acts by withholding budget at a steep contribution cost.

---

## 10. The Three Success Criteria

The brief defines three success criteria. The system makes each one **observable
in-app** and either enforces or monitors it. (Mapping per
[docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §3; values from `metrics.json` and the
marts for the committed scenario.)

| Tier | Criterion | Current | Recommended | Target | Status | Shown in UI |
|---|---|--:|--:|--:|---|---|
| **Primary** | Calibrated **blended ROAS ≥ 4.0×** (enforced floor) | 3.93× | **4.19×** | ≥ 4.0× | **Pass (slack +0.19×)** | Decision Overview guardrails |
| **Secondary** | **NC-CPA ≤ target** and prospecting not starved | — | NC-CPA **$5.51**; prospecting **30.04%** | ≤ $45; ≥ 30.0% | **Pass** (NC-CPA slack); **prospecting binds** | Decision Overview guardrails |
| **Tertiary** | **Eliminate avoidable waste / underspend** (full, efficient utilization) | — | $138,405 deployed, **$0 reserve**; saturated channels cut, capped winners scaled | 100% efficient | **Pass** (growth mode) | Budget Planner / reserve card |

How the website makes the choices observable:

- The **primary** outcome (CM ROAS + net contribution) and the **policy guardrails**
  (blended ROAS vs floor, NC-CPA, prospecting share, reserve) are a **ranked
  scorecard** on Decision Overview, with current vs projected side by side.
- **Marginal-ROAS** logic flags saturated channels (pull back, e.g.
  META_RETARGETING −17.9%) and capped winners (scale up, e.g. GOOGLE_NONBRAND
  +20%), so the tertiary "no avoidable waste" criterion is visible per campaign.
- Flipping to **efficiency-first** mode demonstrates the system *recommending
  holding budget* in reserve rather than forcing inefficient spend.

> The deeper economic objective is **CM ROAS / net contribution** (1.82→1.94×,
> +$17,200/day); the 4.0× blended ROAS is treated as a governance floor (currently
> slack). Both are reported so neither lens hides the other.

---

## 11. Buyer & Inventory Handoff

**Why it matters:** paid media should not drive demand the business cannot fulfil.
A thin, mandatory inventory guardrail closes the buyer/planner loop
([docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §9).

The Buyer & Inventory tab ([`api/inventory_service.py`](backend/api/inventory_service.py),
`GET /api/inventory`) reads the canonical `fact_inventory_snapshot`, joins each SKU
to the campaigns that sell it, and derives a buyer card with these fields:

- **SKU** and **linked campaigns**
- **units on hand**, **forecast daily demand**, **days of cover**
  (`Days of Cover = Units On Hand / Forecast Daily Unit Demand`)
- **estimated stockout date**, suggested **reorder quantity**, **stockout risk**
- **inventory no-scale flag** — set when
  `Days of Cover < Lead Time (14d) + Safety (7d)` (`config.py`
  `INVENTORY_LEAD_TIME_DAYS=14`, `INVENTORY_SAFETY_DAYS=7`).

In the committed scenario, exactly one SKU — **TC-JOG-BLK (Black Active Joggers)**
— breaches the threshold, which sets the no-scale flag on **GOOGLE_PMAX** and pins
it at current spend in the optimizer (`hi = min(hi, current_spend)`), even though
its marginal economics (4.37) would otherwise justify scaling. This is the exact
"attractive but can't fulfil" tension the scenario is designed to demonstrate.

> **Assumptions to label.** The reorder quantity assumes **incoming/open POs = 0**
> (no in-transit replenishment is modelled). This is a **thin guardrail**, not a
> full ERP/procurement system — it exists to stop unsafe scale-ups and produce a
> buyer handoff, nothing more.

---

## 12. Approval, Execution, and Audit

### Marketer-facing approval

The marketer reviews a plan (reason codes, risk flags, uncertainty, binding
constraints) and **approves or rejects** it via
`POST /api/recommendation/{scenario_id}/decision`. Approval **binds to an immutable
snapshot by id** and never re-solves the optimizer. The backend
([`api/store.py`](backend/api/store.py), `backend/api/main.py`) blocks approval when:

- the plan is **infeasible** (422),
- it is **superseded** by a newer plan (409),
- it is **stale** — the data/engine/config/calibration identity changed since it
  was computed (409),
- it is a **sensitivity override** using non-registry-approved coefficients (422).

A recorded decision is an **idempotent terminal** state: replaying the same action
returns the stored decision; a conflicting action returns 409. There is **no
delete/rollback** — a reversal would be a new compensating decision (the ledger is
append-only).

### Stub execution

Approve generates **stubbed** Meta/Google set-budget payloads
(`execution_events[].is_stub=true`), previewable read-only via
`GET /api/recommendation/{id}/execution-preview`. **No real OAuth, no live budget
writes** — the ledger persists decisions but does not call platform APIs
([README.md](README.md)).

### Audit ledger and marts

Decisions are written to a **durable, append-only, hash-chained** SQLite ledger
that survives restarts and is **tamper-evident** (`GET /api/audit/verify` recomputes
the chain). Each record retains full provenance: `scenario_id`, `rec_id`,
`data_fingerprint`, `engine_version`, `config_fingerprint`,
`calibration_fingerprint`, `effective_calibration_fingerprint`, the constraint set,
solver status/iterations, and binding/violated/slack constraint counts
([mart_decision.csv](reports/marts/mart_decision.csv)).

Four **Looker-ready SQL marts** (single-grain views) are exported to DDL + CSV via
`make marts` and served at `/api/marts/{name}`
([reports/marts/MANIFEST.json](reports/marts/MANIFEST.json), `marts.sql`):

- `mart_decision` — one row per decision (with full provenance).
- `mart_decision_line` — one row per campaign allocation line.
- `mart_binding_constraint` — one row per binding/slack constraint with detail.
- `mart_audit_chain` — the hash-chain integrity record (`head_hash`, `count`, `ok`).

For the committed scenario the chain is `ok=true`, count 1, head
`SCN-e34a94f8174ffc70` ([MANIFEST.json](reports/marts/MANIFEST.json)).

---

## 13. Model Evidence and Technical Q&A Surface

The **Model Evidence** tab (`ModelEvidence.tsx`, `GET /api/model-evidence`,
`model-evidence.v2`) is a curated, **latent-truth-stripped** window onto the model
report, with a **fresh/stale verdict** computed against the active recommendation's
modeling identity (`evidence_input_fingerprint`, e.g. `8f984b5049c4a8ef`). It
exposes:

- **Champion Selection Explorer** — per campaign: the pre-test fold wins, WAPE
  bars (XGBoost vs each baseline), and the promotion/fallback reason; clearly
  separating **pre-test selection evidence** from **untouched-test evaluation**.
- **Forecast Accuracy workbench (interactive)** — built from a persisted row-level
  artifact `reports/model_performance/test_predictions.csv` (D-045):
  - a **forecast-vs-actual fan** per campaign (P10–P90 band, P50 champion line,
    actuals coloured in/out of band, hover tooltip), and
  - an **actual-vs-predicted scatter** (45° reference line, points coloured by band
    coverage, axes auto-zoomed, mean-bias annotated).
- **Drift warnings** — the holdout-drift campaigns (GOOGLE_PMAX, META_RETARGETING)
  surfaced as retraining signals.

The persisted CSV is exactly the tidy test rows the report PNGs already draw from
(per campaign × untouched-test day: `date`, realized `y`, `pred`, the deployed band,
`residual`, `model`, a `covered` flag). It carries **no** latent generator-truth, so
exposing it has no leakage risk. When the file is absent (an older report), the API
returns `series_available=false` and the UI falls back to bars.

**Live interactive vs static report PNGs.** The forecast fan and actual-vs-predicted
views are **live interactive** in-app. The deeper diagnostic plots remain **static
report artifacts** in `reports/model_performance/plots/` (generated by
`make model-report`): `01_actual_vs_predicted`, `02_residuals_vs_predicted`,
`03_error_by_campaign`, `04_forecast_fan`, `05_marginal_roas_recovery`,
`06_interval_reliability`, `07_optimizer_sensitivity`, `08_allocation_recommendation`.
These — especially the latent-marginal recovery (§8 of the report) and the
optimizer-sensitivity grid — are intentionally kept in the **technical report**
rather than the marketer workflow, because they reference offline latent truth and
model-internal stress tests that are not part of the normal decision surface.

The report's own verdict line is honest about scope: **Safe for MODEL demo: True**
(forecast + response fidelity); **Safe for DECISION demo: False** in the sense that
the decision basis is the marginal ordering + ROAS floor, **not** the P10/P90 band
([REPORT.md](reports/model_performance/REPORT.md) §11).

---

## 14. Architecture

### Components

- **Frontend** — Vite + React 19 + TypeScript SPA ([`frontend/`](frontend/),
  Tailwind v4, lucide-react). A read-and-govern client; owns no business logic.
- **Backend** — FastAPI + Python single service ([`backend/api/`](backend/api/)),
  typed REST contracts (Pydantic). Single-backend by design (no Express).
- **Decision engine** — deterministic Python package
  ([`backend/decision_engine/`](backend/decision_engine/)): synth generator,
  schemas, ingestion, engine (forecast / response / optimizer), economics,
  calibration.
- **Data / analytics** — DuckDB + pandas over canonical CSV/Parquet artifacts.
- **Model & report artifacts** — `reports/model_performance/` (metrics, plots,
  row-level predictions), `reports/economics/`.
- **Audit marts** — durable hash-chained SQLite ledger → 4 Looker-ready SQL marts
  (`reports/marts/`).

### Data flow

```mermaid
flowchart TD
    metaRaw["Meta data/paging JSON"] --> adapters["Platform adapters (ingestion)"]
    googleRaw["Google nested results JSON"] --> adapters
    shopifyRaw["Shopify commerce JSON"] --> adapters
    adapters --> validate["Pandera/Pydantic validation + quarantine"]
    validate --> canonical["Canonical model (13 tables, DuckDB)"]
    canonical --> measure["Measurement prep: dedup, attribution, calibration registry"]
    measure --> modelA["Model A: XGBoost quantile BAU forecast (P10/P50/P90)"]
    measure --> modelB["Model B: orthogonalized adstock response (marginal ROAS)"]
    modelA --> combine["Combined: Y_BAU(b_current) + [R(b) - R(b_current)]"]
    modelB --> combine
    combine --> optimizer["SLSQP optimizer (objective + constraints + feasibility)"]
    inventory["Inventory snapshot (no-scale guards)"] --> optimizer
    economics["Contribution economics (margins, hurdles)"] --> optimizer
    optimizer --> rec["Recommendation + reason codes + risk flags + fingerprints"]
    rec --> human["Human approve / reject"]
    human --> exec["Stub execution payloads (is_stub=true)"]
    human --> ledger["Hash-chained audit ledger -> SQL marts"]
    rec --> api["FastAPI endpoints"]
    api --> ui["Vite + React SPA (7 tabs)"]
```

### Key endpoints ([`backend/api/main.py`](backend/api/main.py))

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness |
| `GET /api/ingestion` | Feed health, DQ issues, SKU resolutions |
| `POST /api/sku-resolution/{id}/approve` | Approve a needs-approval SKU mapping |
| `GET /api/calibration/registry` | Calibration entries + provenance |
| `GET /api/recommendation` | Solve the optimizer for (validated, editable) constraints; store snapshot |
| `GET /api/recommendation/{id}/execution-preview` | Read-only stubbed set-budget payloads |
| `POST /api/recommendation/{id}/decision` | Approve / reject (idempotent, guarded) |
| `GET /api/recommendation/{id}/audit` | Stored decision for a scenario |
| `GET /api/audit/log` | Full append-only decision ledger |
| `GET /api/audit/verify` | Hash-chain integrity |
| `GET /api/marts` , `GET /api/marts/{name}` | Looker-ready marts over the ledger |
| `GET /api/inventory` | Buyer & inventory handoff |
| `GET /api/model-evidence` | Curated model evidence (`model-evidence.v2`) |
| `POST /api/admin/reset` | Demo-only state reset (would be gated/removed in prod) |

### Important directories

```
backend/decision_engine/   deterministic engine package
  config.py                seed, paths, policy constants
  schemas/                 canonical.py (Pandera) + envelopes.py (Pydantic)
  synth/                   scenario truth, generator, defects, fingerprint
  ingestion/               adapters, quality, pipeline, sku_resolution
  engine/                  bau_forecast, selection, baselines, response,
                           optimizer, intervals, recommend, data
  economics.py             derived break-even / scale floor + latent helpers
  calibration/             incrementality calibration registry
  eval/                    report, metrics, plots, harness, provenance
backend/api/               FastAPI shell + services (recommendation, ingestion,
                           store, marts, inventory, model_evidence, calibration)
frontend/              Vite + React 19 web UI (7-tab client)
scripts/                   generate, model_report, economics_report, cm_sweep, marts
data/                      generated artifacts (gitignored)
reports/                   model_performance / economics / marts artifacts
tests/                     engine + API test suite
docs/                      FINAL_PLAN, DECISIONS, AI_WORKFLOW, UI_INTEGRATION_MAP
```

---

## 15. AI-Assisted Development Workflow

The brief evaluates *how* the prototype was built with AI. The AI-workflow signal
lives in **how the system was built**, not in fragile live agentic behaviour
(there is **no** runtime orchestration agent). Source:
[docs/AI_WORKFLOW.md](docs/AI_WORKFLOW.md).

### Tools used (only what is evidenced in the repo)

- **Claude Code (Opus during development)** — the primary builder: schema
  contracts, deterministic generator, defect catalog, tests, docs, and the
  staged engine/UI work.
- **A second AI reviewer (Codex)** — audited Stage 0; each finding was verified
  against the code before acting.
- **Deterministic Python (numpy / pandas / Pandera / Pydantic / scipy / xgboost)**
  does all numerical work. The **runtime LLM is Stage 5 — planned, not built**;
  when added it is bounded to ranking allowed SKU candidates and narrating
  already-computed results (`claude-sonnet-4-6`), with a deterministic template
  fallback for every feature.

### What AI generated vs. where the human intervened

AI generated UI scaffolding, code, tests, and report/plan drafting. Human
interventions and **rejected/changed AI suggestions** (all from
[docs/AI_WORKFLOW.md](docs/AI_WORKFLOW.md)):

- **Rejected: business reasoning inside the LLM.** Moved all numeric decisions
  into deterministic services; the LLM only ranks allowed candidates / narrates
  validated output. (The rehearsed Q&A line.)
- **Corrected: latent-truth leakage.** `scenario_truth` was being written into
  `data/canonical` (a target-leakage risk); fixed to keep it in memory / behind an
  opt-in flag, with isolation tests (D-009).
- **Corrected: model-selection / feasibility leakage in a test helper.** A greedy
  marginal-rank helper "proved" a number while ignoring the very constraints the
  system advertises (it scaled inventory-constrained PMax and starved
  prospecting). Replaced with a constraint-valid feasibility enumeration.
- **Corrected: magic hurdle constant.** Replaced a `2.8` efficiency constant with
  an **economic derivation** (break-even = 1/margin × safety); the derivation
  validated the old number (2.754 ≈ 2.8) but is now principled and tested (D-007).
- **Corrected: knife-edge / unreachable ROAS.** Re-tuned the scenario via throwaway
  search scripts so the 4.0× crossing emerges from the data over a broad band, not
  a hardcoded number (D-008).
- **Kept the deterministic backend as the source of truth**, added
  governance/audit, and kept latent truth out of all product payloads.

> **Meta-lesson captured in the docs:** "a green review comment is not the same as
> in-scope work" — two review rounds nearly walked the build past its stage
> boundary one good fix at a time; those were deferred to their proper stages with
> the rationale preserved in `docs/DECISIONS.md`.

---

## 16. Testing, Validation, and Reproducibility

### Run commands ([Makefile](Makefile), [README.md](README.md))

```bash
make setup        # python3.13 venv + EXACT locked deps (requirements-lock.txt)
make generate     # write BOTH datasets: realistic (primary) + golden (benchmark)
make test         # pytest tests/ (engine + API; hard-pinned to the golden benchmark)
make fingerprint  # print + verify the full-artifact fingerprint
make verify-clean-install   # throwaway venv from the lock: generate + test

make api          # FastAPI backend  -> http://127.0.0.1:8000  (docs at /docs)
make web-setup    # one-time: install web UI deps
make web          # Vite dev server  -> http://localhost:3000

make model-report # reproducible forecast/response/optimizer report (metrics.json + plots + CSVs)
make econ-report  # contribution-economics report (waterfall, hurdles, sensitivity)
make cm-sweep     # read-only CM-ROAS floor policy sweep
make marts        # Looker-ready SQL marts (DDL + CSV) from the audit ledger
```

> **XGBoost needs the OpenMP runtime** (not pip-installable): macOS
> `brew install libomp`; Debian/Ubuntu `apt-get install libgomp1`.

### What is validated

The test suite asserts **business invariants and tolerance ranges**, not one exact
allocation ([docs/FINAL_PLAN.md](docs/FINAL_PLAN.md) §13): envelope schemas reject
malformed nesting and bad money fields; `cost_micros` normalizes; duplicates don't
double-count; unapproved SKU matches are never auto-included; label maturity
excludes immature 7-day outcomes; chronological folds + 7-day gap prevent leakage
and residuals are out-of-fold; XGBoost is only promoted if it beats baselines;
quantile crossing is measured; total budget (incl. reserve) is preserved exactly;
every optimizer constraint holds and prospecting minimum cannot be violated;
contradictory constraints yield an explicit conflict report (never an invalid
plan); stockout-risk SKUs cannot receive increases; recommendations are
deterministic; a rejected plan cannot execute and approval is idempotent; the LLM
cannot modify numeric fields; saturation/extrapolation tests behave as designed.
(Determinism note: engine runs with fixed seeds and `n_jobs=1`.)

### Fingerprints / seeds / reproducibility

`MASTER_SEED = 20240117`; engine `stage3.5`; report `report.v1` / `stage4.5`
(`MANIFEST.json`); profile `realistic`. The **full-artifact fingerprint** (tables +
Meta/Google/Shopify envelopes + versions + seed + deps) is the main reproducibility
hash, with a separate canonical-tables-only fingerprint. Both profile fingerprints
are pinned in `tests/test_fingerprints.py`; **golden's must not move unless
intentional**. Pinned dependency versions (from `REPORT.md`): python 3.13.11,
numpy 2.4.6, pandas 3.0.3, scipy 1.17.1, scikit-learn 1.9.0, xgboost 3.3.0,
matplotlib 3.11.0. The model report is byte-reproducible (run `make model-report`
twice for identical `metrics.json`).

### Known warnings / honest notes

- Some campaign-level **holdout drift** (GOOGLE_PMAX, META_RETARGETING) is surfaced
  as a retraining signal, not auto-corrected.
- The **deployed interval is a mixed policy** (conformal + ±20% heuristic), so its
  coverage is empirical, not a single calibrated band.
- All metrics validate the **machinery on synthetic data**, not real performance.

---

## 17. Limitations

- **Synthetic data.** Every dataset is deterministic synthetic; errors are far
  smaller than real paid-media noise.
- **No causal identification.** Response estimates are observational/local;
  residualization reduces but does not eliminate confounding. The latent-truth
  recovery is an offline check of the generator, not causal proof.
- **No real OAuth / write-back.** Execution payloads are **stubbed**
  (`is_stub=true`); nothing is pushed to Meta/Google.
- **Forecast history length.** ~210 days; insufficient for yearly seasonality
  (hence Fourier + flags rather than Prophet); intervals are display-only.
- **Campaign-level drift.** Two XGBoost champions regressed on the untouched test.
- **Inventory assumptions.** Reorder qty assumes open POs = 0; it is a thin
  guardrail, not full ERP/procurement.
- **Calibration error is synthetic.** The registry copies the scenario's true
  incrementality; the sensitivity lever stresses it but it is not measured lift.
- **Platform scope.** Meta + Google only; Amazon/Microsoft are roadmap.
- **LLM not yet built.** Stage 5 is planned and bounded; no LLM currently
  participates in any numeric decision.
- **Demo reset endpoint.** `POST /api/admin/reset` exists for the demo and would be
  removed/gated in production.

---

## 18. Future Work / Production Roadmap

- **Real Meta/Google OAuth ingestion** and scheduled refresh (replace synthetic feeds).
- **Shopify / GA4 truth integration** for real commerce reconciliation.
- **Experiment-based calibration** — geo-lift / conversion-lift to replace synthetic
  incrementality coefficients (the only path to causal claims).
- **Drift monitoring + governed retraining** triggered by the holdout-drift signals.
- **Row-level evidence and richer Model Evidence workbenches** (residual explorer,
  calibration/marginal-recovery views, optimizer-perturbation UI, CSV downloads,
  browser-triggered report regeneration) — the deferred "Phase E" items.
- **Execution rollout with rollback** — shadow → limited copilot → live writes with
  compensating-decision reversals.
- **Inventory / PO integration** — model in-transit replenishment instead of POs = 0.
- **Permissions / approval roles** — multi-user governance.
- **Amazon / Microsoft adapters** — same connector + canonical-schema pattern, no
  new decision logic.
- **Prophet / NeuralProphet** for multi-year histories; **SHAP** for BAU driver
  explainability (post-core stretch).
- **LookML / BI** on top of the existing SQL marts.

---

## 19. Appendix

### A. File map (selected)

| Area | Path |
|---|---|
| Canonical plan / decisions | [docs/FINAL_PLAN.md](docs/FINAL_PLAN.md), [docs/DECISIONS.md](docs/DECISIONS.md) |
| AI workflow / UI map | [docs/AI_WORKFLOW.md](docs/AI_WORKFLOW.md), [docs/UI_INTEGRATION_MAP.md](docs/UI_INTEGRATION_MAP.md) |
| Policy constants | [backend/decision_engine/config.py](backend/decision_engine/config.py) |
| Economics | [backend/decision_engine/economics.py](backend/decision_engine/economics.py) |
| Ingestion | [backend/decision_engine/ingestion/](backend/decision_engine/ingestion/) |
| Engine | [backend/decision_engine/engine/](backend/decision_engine/engine/) |
| Calibration registry | [backend/decision_engine/calibration/registry.py](backend/decision_engine/calibration/registry.py) |
| API | [backend/api/main.py](backend/api/main.py), [backend/api/store.py](backend/api/store.py) |
| Web UI | [frontend/src/](frontend/src/) |
| Reports | [reports/model_performance/](reports/model_performance/), [reports/economics/](reports/economics/), [reports/marts/](reports/marts/) |

### B. API endpoints

See [§14](#14-architecture). Live contract details in
[docs/UI_INTEGRATION_MAP.md](docs/UI_INTEGRATION_MAP.md).

### C. Report artifacts

- `reports/model_performance/`: `metrics.json`, `REPORT.md`,
  `per_campaign_point_metrics.csv`, `test_predictions.csv`, `plots/01..08_*.png`.
- `reports/economics/`: `ECONOMICS.md`, `CM_FLOOR_SWEEP.md`, `CM_FLOOR_SWEEP.json`.
- `reports/marts/`: `MANIFEST.json`, `marts.sql`, `mart_decision.csv`,
  `mart_decision_line.csv`, `mart_binding_constraint.csv`, `mart_audit_chain.csv`.

### D. Key metrics table (committed scenario, realistic profile)

| Metric | Value | Source |
|---|--:|---|
| Scenario id / rec id | `SCN-e34a94f8174ffc70` / `REC-OPT-0001` | `mart_decision.csv` |
| Daily spend | $138,405 | `metrics.json`; marts |
| CM ROAS | 1.82× → 1.94× | `metrics.json` `cm_roas_*` |
| Net contribution / day | $112,980 → $130,180 | `metrics.json` `net_contribution_*` |
| Calibrated blended ROAS | 3.93× → 4.19× (floor 4.0×) | `ECONOMICS.md`; `metrics.json` 4.1929 |
| NC-CPA | $5.51 vs $45 (slack) | `mart_binding_constraint.csv` |
| Prospecting share | 30.04% vs 30.00% (binds) | `metrics.json`; `REPORT.md` §10 |
| Forecast WAPE (selected) | 0.11098 | `REPORT.md` §3 |
| Response Spearman / sign acc | 0.964 / 0.857 | `REPORT.md` §8 |
| Conformal coverage (target 0.80) | raw 0.397 → calibrated 0.806 | `metrics.json` `forecast.overall.conformal` |
| Seed / engine / profile | 20240117 / stage3.5 / realistic | `config.py`; `metrics.json` |

### E. Glossary

- **Blended ROAS** — total revenue ÷ total ad spend across campaigns.
- **Calibrated (blended) ROAS** — same ratio computed on **incremental** revenue
  after the calibration registry adjustment; the enforced 4.0× governance floor.
- **CM ROAS** — contribution dollars per ad dollar (`Σ mᵢ·Rᵢ ÷ Σ bᵢ`); break-even
  at 1.00×; the optimizer's headline economic lens.
- **Net contribution** — `Σ mᵢ·Rᵢ − Σ bᵢ` (contribution after ad spend); the
  optimizer's objective.
- **NC-CPA** — new-customer cost per acquisition; a monitored ceiling guardrail.
- **Marginal CM ROAS** — contribution return on the **next** dollar; the
  scale/hold/cut rule uses a uniform 1.05× marginal hurdle.
- **Conformal interval** — a held-out-calibrated prediction band (CQR) targeting
  80% coverage; display-only here.
- **Champion model** — the per-campaign deployed model chosen by the frozen
  pre-test selector (XGBoost only if it materially beats the baseline).
- **Reserve** — budget intentionally **not** deployed in efficiency-first mode when
  no campaign clears the marginal hurdle.
- **Stale scenario** — a stored plan whose data/engine/config/calibration identity
  no longer matches the live engine; cannot be approved.
- **Inventory no-scale** — a guard that pins a campaign at current spend when its
  SKU's days of cover fall below lead + safety days.

---

*All numeric values in this report trace to the cited repo files and generated
artifacts (realistic profile, engine `stage3.5`). They validate the modeling and
decision machinery on synthetic data and imply no real-world performance or causal
identification.*

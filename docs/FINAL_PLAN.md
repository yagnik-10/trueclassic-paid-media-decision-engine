# True Classic — Paid Media Decision Engine
### Final consolidated architecture & build plan

An auditable, vendor-neutral cross-platform paid-media **decision & governance layer**.

This is the version we locked after pressure-testing every choice and selectively harvesting the strongest implementation details from the comparison plan. It is deliberately *narrow, real, and runnable end-to-end* — which the brief explicitly rewards over broad mockups.

---

## 0. The one-sentence thesis

> A transparent, vendor-neutral decision loop that turns fragmented media + commerce data into **risk-aware, marginal-economics budget recommendations**, while keeping measurement inputs, business constraints, human approval, and execution adapters **independently replaceable**.

**Sharp on the thesis, humble on the execution boundary.** The system has a point of view (optimize risk-adjusted contribution *at the margin*, expose uncertainty, keep a human in the loop, make every decision auditable). The *execution* layer is pluggable — approved envelopes can route to native platform APIs **or an existing engine**.

---

## 1. Positioning (read this before writing slides)

True Classic and its technology partners publicly describe the brand as AI-native and report sophisticated execution automation. Frame this as **alignment, not revelation** — do **not** present "optimize business outcomes, not platform ROAS" or contribution-margin thinking as a discovery; public materials indicate that this orientation already exists in their operating philosophy.

**Grounding facts (verified, but handle with care):**
- The role (True Classic "AI Solutions Architect," Calabasas) explicitly names **Python, React, Node.js, Express.js, REST APIs, AWS/Heroku, GitHub CI/CD, LLMs (Claude named first), and "a systems thinker who can architect end-to-end solutions."** → This is why the stack is full-stack, not a notebook.
- Triple Whale's (vendor-authored) materials say True Classic runs Meta spend through **Moby** automations and manages **$3M+/month**, with a measurement layer (**Compass**: MTA + MMM + incrementality, calibrated). Treat as **context, not causal proof.** The 36% uplift is marketing. Their own materials are internally inconsistent on revenue (nine-figure in one place, ">$1B" in another) — **do not assert $1B**, and do not infer the company's motivations or why the role exists.

**Positioning do/don't:**
- ✅ "I kept execution pluggable because brands at this scale often already have pacing/activation systems; this prototype focuses on the transparent decision contract between measurement and execution."
- ❌ "This is the layer above Moby so you can stop renting a black box." (Presumptuous; implicitly critiques a vendor their CEO champions.)
- **Moby is not on the primary business slide.** One confident, non-presumptuous line in architecture narration; go deeper only if asked.

---

## 2. Scope (locked)

| Dimension | Decision |
|---|---|
| Platforms (built) | **Meta + Google** only. Amazon/Microsoft live in the architecture & roadmap, not the committed implementation. |
| Input shape | **API-envelope-shaped synthetic JSON**, not pre-flattened tables: Meta-style `data/paging` and Google-style nested `results` with `campaign`, `metrics`, and `segments`. Adapters flatten these into the canonical model. |
| Optional ingestion stretch | If already-working Amazon/Microsoft connectors can be ported with negligible effort, they may appear only in the ingestion/unification page. They remain excluded from forecasting and allocation and are cut before any core feature slips. |
| Products | **4 real True Classic product names** (e.g. Black Crew Neck Tee, Classic Polo, Black Active Joggers, Staple Crew 6-Pack). All economics **synthetic and labeled**. |
| Campaigns | ~6–8 (e.g. Meta: Broad Prospecting, Advantage+ Shopping, Dynamic Retargeting; Google: PMax, Nonbrand Search, Brand Search, Shopping). |
| Data | ~180–270 days of **deterministic synthetic** daily data (~1–2k campaign-day rows). |
| Writes | **Stubbed** execution payloads + audit. No real OAuth, no live budget mutations. |

**Transparency rule:** README states plainly what is real (the pipeline, models, optimizer, app, audit) vs. stubbed (the data and the execution calls).

**Implementation details intentionally harvested from the comparison plan:** realistic Meta/Google API envelopes; simple forecasting baselines; 7-day validation gap; conversion-label maturity handling; lightweight Looker-ready SQL marts; Pydantic/offline LLM fallback; and SHAP only as a post-core stretch. These additions do not change the locked architecture.

---

## 3. Success metrics → how the system serves each

| # | Metric (from brief) | How the system addresses it |
|---|---|---|
| 1 (Primary) | **Blended ROAS ≥ 4.0×** | Displayed as a headline KPI **and enforced as a hard constraint**. The optimizer does *not* maximize ROAS (ratios → pathological low-spend); it maximizes risk-adjusted net contribution **subject to** the ROAS floor. |
| 2 (Secondary) | **NC-CPA ≤ target** | Prospecting vs. retargeting modeled as **separate segments**; NC-CPA is an optimizer **ceiling constraint** + a **prospecting-minimum** floor, so the system can't inflate blended ROAS by starving the top of funnel. |
| 3 (Tertiary) | **100% efficient utilization** | **Marginal-ROAS** logic flags both saturated channels (pull back) and capped winners (scale up). The **reserve line** + efficiency-first mode let it *recommend holding budget* rather than forcing inefficient spend. |

**The conceptual spine:** *marginal ROAS, not average ROAS.* A 6× historical channel may be saturated; a 4× channel may have profitable room. Allocation depends on the **next dollar's** expected return. This one idea drives all three metrics.

---

## 4. System architecture

```
Meta API-shaped JSON ─────┐
                           ├── Platform adapters
Google API-shaped JSON ────┘
                     ↓
          Schema validation + quarantine        (Pandera contracts)
                     ↓
              Canonical media model
       ┌─────────────┼─────────────┐
       │             │             │
    SKU spine    DTC commerce outcomes   Inventory snapshot
   (+ aliases)   (Shopify source of record)
       └─────────────┼─────────────┘
                     ↓
        MEASUREMENT PREPARATION  (three explicit stages)
        • deduplication            (walled gardens double-count)
        • attribution normalization (7d-click vs 14d vs last-touch)
        • incrementality calibration registry (provenance + confidence)
                     ↓
        MODEL A — XGBoost quantile BAU forecast
        "What happens if the current plan continues?"  → P10/P50/P90
                     ↓
        MODEL B — residualized, segment-level adstock–Hill response
        "What changes when spend changes?"  → anchored delta only
                     ↓
        Combined scenario:  Ŷ(b) = Ŷ_BAU(b_current) + [R(b) − R(b_current)]
                     ↓
              SLSQP optimizer
        • objective: risk-adjusted net contribution
        • constraints: ROAS floor · NC-CPA ceiling · prospecting min
          · inventory limits · movement & support bounds
          · optional explicit reserve line
                     ↓
        Feasible recommendation OR explicit constraint-conflict report
                     ↓
        Recommendation + reason codes + risk flags
                     ↓
        Human approve / edit / reject
                     ↓
        Pluggable stub execution adapters  →  Audit trail

Bounded LLM sidecar (off the critical path):
   • rank approved SKU candidates
   • narrate validated recommendations
   • (optional) parse NL constraints → human confirmation
```

---

## 5. The model design (the hard-won core)

### Model A — Business-as-usual (BAU) forecast
- **XGBoost quantile regression**, P10/P50/P90, for 7-day **net revenue** and **new customers**, at the **current** operating point.
- **Monotonic constraint** on feasible spend (directional sanity), but understood to be **trustworthy only within observed support**.
- Features: current spend, adstocked spend, platform, campaign, objective, SKU, prospecting/retargeting flag, day-of-week, promo flag, holiday flag, **Fourier terms**, rolling & lagged metrics, budget utilization, noon pacing, CPC/CTR/CVR trends, inventory-availability flag.
- **Forecast-horizon and label maturity:** predict a direct 7-day outcome; exclude or down-weight rows whose conversion labels have not had time to mature. The cutoff policy is explicit and tested.
- **Time-aware validation:** use chronological walk-forward validation. For a 7-day target, use a **7-day gap** between train and validation windows so overlapping future labels cannot leak across the boundary. Preserve the history required to compute lag/adstock features.
- **Visible baselines:** compare XGBoost against at least trailing-14-day spend-normalized ROAS and same-weekday-last-week. The learned model is promoted only if it materially beats the appropriate simple baseline; otherwise the baseline remains the safe fallback.
- **Quantile coherence:** train/evaluate quantiles on shared folds and monitor crossing rate. Use calibrated or joint quantile methods where practical; any monotone rearrangement/post-hoc ordering is only a final safety guard and is logged — never the primary calibration story.
- **Explainability stretch:** SHAP may be added after the core flow works, to explain BAU drivers. It is not load-bearing for the optimizer or demo.
- **No Prophet.** With <1 year of data its yearly seasonality is inert; calendar structure is captured transparently via Fourier + flags. *(Prophet/NeuralProphet noted on the production roadmap for multi-year histories — recovers the vocabulary at zero demo cost.)*

### Model B — Spend-change response
- A **jointly estimated set of adstock–Hill response functions** across **segments** (Meta prospecting / Meta retargeting / Google brand / Google nonbrand-Shopping), with campaign-specific scale, operating point, and bounds. Curves are not fit independently or per campaign: joint estimation reduces the chance that correlated channels each receive credit for the same residual demand, while per-campaign curves would imply precision we do not have on ~180 synthetic days.
- Form: geometric adstock → Hill saturation `R(s) = β · a(s)^α / (γ^α + a(s)^α)`.
- **Contributes only a delta**, anchored at current spend → `R(b) − R(b_current)`, which is **0 at b_current** by construction. Therefore the seam is clean and the two models **cannot emit conflicting absolute forecasts**: BAU owns the level (incl. current media); Model B owns the counterfactual change.

### Estimation: chronologically cross-fit controls, then jointly fit response
The Hill model must not attribute seasonal/promo demand to media (holidays raise demand *and* spend rises into them).
1. **Control model** on pre-treatment, non-media structure (day-of-week, trend, promo, holiday, price/discount, availability, site outages, and carefully defined organic proxies) → `Ŷ_control`. Do **not** control for paid clicks, paid sessions, or other variables caused by advertising.
2. Generate **chronological out-of-fold control predictions** using blocked/walk-forward splits with the required gap; do not create residuals from in-sample fitted values.
3. Compute out-of-fold residuals: `Y_residual = Y − Ŷ_control_oof`.
4. Fit all segment-level adstock–Hill components **jointly** to the same residual outcome, with bounded parameters, regularization, multiple deterministic initializations, and block-bootstrap uncertainty.
5. Fit the final control/response artifacts on the full eligible training period only after validation.

> **README must state** that the combiner adds only the *delta* from Model B, so current-environment effects live in BAU and aren't counted twice. Pre-empts "are you modeling spend twice?" Residualization reduces but does not eliminate observational confounding; production calibration still requires lift experiments.

### Seam consistency diagnostic (NOT a tree derivative)
A gradient-boosted tree is piecewise-constant → its analytic spend-derivative is ~0/undefined. **Do not differentiate it.** Instead compare an **in-support finite difference**:
`S_XGB = [Ŷ(1.05·b) − Ŷ(0.95·b)] / (0.10·b)`  vs. the Hill marginal `dR/db |_{b_current}`.
Treat as a **diagnostic, not a constraint**. Flags: `CONSISTENT` / `DIRECTION_MISMATCH` / `MAGNITUDE_DIVERGENCE` / `INSUFFICIENT_SPEND_SUPPORT`. *(The ±5% secant is also the more appropriate comparison object — it averages over the same local region the marginal summarizes.)*

### Extrapolation discipline
A parametric curve degrades **gracefully** outside support (keeps curving vs. flattening to a tree artifact) — but it does **not** create information.
- Recommendations bounded to **~±20%** per campaign per cycle.
- Compute & display **historical spend support** (current point vs. percentiles).
- **Block or flag** scenarios outside support; optimizer cannot recommend beyond approved bounds.

### Uncertainty propagation
Don't carry BAU quantiles through unchanged after moving spend.
- **MVP:** bootstrap Hill parameters; for each candidate allocation sample BAU outcome + bootstrap response delta, sum → scenario P10/P50/P90.
  `Y^(k)(b) = Y_BAU^(k) + [R^(k)(b) − R^(k)(b_current)]`
- **Fallback** if too heavy: **Expected mode** (P50 + median response) vs. **Conservative mode** (lower BAU quantile + downside response).
- *Caveat to state:* convolving the two implicitly treats them as independent — defensible (different signal: level vs. residual-slope), not exact.

---

## 6. Optimizer

- **SciPy SLSQP** (bounds + equality & inequality constraints; same algorithm PyMC-Marketing/Robyn use — defensible under questioning).
- **Objective:** maximize `Σᵢ [ R̂ᵢ(bᵢ)·mᵢ − bᵢ − risk_penaltyᵢ ]` — risk-adjusted net contribution (`mᵢ` = pre-ad contribution-margin rate).
- **Budget as a ceiling with an explicit reserve line:** `Σ bᵢ + b_reserve = B`. Money never silently vanishes from the UI.
  - **Growth-plan mode:** `b_reserve = 0` (deploy full approved budget — clearest cross-channel reallocation story).
  - **Efficiency-first mode:** `b_reserve ≥ 0` (hold budget when no campaign clears the marginal floor — the waste-control story).
- **Constraints:** total = B (incl. reserve); blended ROAS ≥ 4.0×; NC-CPA ≤ target; prospecting ≥ min share; per-campaign movement ≤ ±20%; minimum learning budgets; **inventory-risk campaigns cannot scale**; campaigns below marginal-ROAS floor get no increase; (optional) cap simultaneous changes.
- **Feasibility handling:** run a constraint-feasibility check before optimization. If the ROAS floor, NC-CPA ceiling, prospecting floor, inventory restrictions, and movement bounds cannot all be satisfied, return an explicit infeasibility report identifying the conflicting constraints. Never silently emit an invalid plan. Offer either (a) the closest feasible plan with quantified shortfalls or (b) a marketer-confirmed constraint relaxation, then rerun.

---

## 7. Measurement: three separate adjustments (never one "haircut")

A single platform-vs-Shopify discrepancy ratio is indefensible. Keep distinct layers:
1. **Deduplication** — multiple platforms may claim the same order; Shopify provides the observed DTC order/revenue source of record used for reconciliation, not a universal attribution model.
2. **Attribution normalization** — incompatible windows/models (Meta 7d-click/1d-view, Google data-driven/last-click, Amazon 14d last-touch).
3. **Incrementality calibration registry** — coefficient **+ source + effective period + confidence + scope**, every value **explicitly synthetic** (standing in for geo-lift / conversion-lift / MMM / a measurement vendor / finance-approved factors).

**Show sensitivity, not a staged reveal.** UI offers **Platform-reported** vs **Calibrated decision** views. The message is *"the optimizer is measurement-agnostic; here's how the recommendation changes when the approved calibration source changes"* — not *"retargeting was secretly bad."*

---

## 8. LLM scope (bounded, off the critical path)

Numbers come from deterministic code; the LLM never computes, allocates, or executes. **Every LLM feature has a deterministic template fallback so an API outage can't break the demo.**

1. **SKU-resolution assistant** — deterministic matching produces an `allowed_candidates` list; the LLM **ranks** them with evidence. Schema **rejects any SKU not in the list** → it cannot invent one. Human approves the mapping.
2. **Recommendation narrator** — receives immutable optimizer output; emits a 2–3 sentence explanation. **Displayed numbers render from app state, not from LLM prose.**
3. *(Optional, 3rd priority)* **NL constraint parsing** — sentence → structured proposal → Pydantic validation → **visible confirmation form → human confirms** → optimizer. Never runs silently. Sliders remain the primary control.

**No runtime orchestration agent.** The AI-workflow signal lives in *how you built it* (Claude Code prompts, generated tests, rejected suggestions, manual corrections — capture in `AI_WORKFLOW.md`), not in fragile live agentic behavior.

---

## 9. Inventory (thin guardrail, mandatory)

The brief explicitly lists "replenishment recommendation" and "buyer view," and maps technical choices to fulfillment cost — and "don't drive demand you can't fulfill" is a legitimate paid-media constraint. Keep it tiny (~10% of build, 30–45s of demo):
- `Days of Cover = Units On Hand / Forecast Daily Unit Demand`.
- If `Days of Cover < Lead Time + Safety Days` → **no-scale flag** on that SKU's campaigns; show estimated stockout date + suggested reorder qty.
- Fulfillment + return reserves feed contribution economics.
- One **buyer/planner card or toggle**. **Not** a second inventory product with its own forecasting.

---

## 10. Tech stack (final)

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js + TypeScript + shadcn/ui + Recharts** | Matches the role's React/Node direction; real approval UX; demonstrates product engineering. Thin (~5–6 screens). |
| Backend | **FastAPI + Python** | Decision engine lives where XGBoost/SciPy/pandas live; typed REST contracts. |
| Data | **DuckDB + pandas** | API-shaped JSON is flattened by adapters, then stored/queryable as canonical DuckDB tables and Parquet/CSV artifacts. Fast local analytics, SQL-inspectable in Q&A, no external DB. **pandas only** (Polars pointless at ~2k rows). |
| Validation | **Pandera** (tabular) + **Pydantic** (API) | |
| Modeling | **XGBoost** (quantile + monotonic), **SciPy SLSQP**, bootstrap for response params | |
| LLM | **Claude** (Sonnet for narration/ranking; Code/Opus during dev) — exact model string in README | Role names Claude first. |
| Packaging | One-command local start, **deployed backup**, optional Docker Compose, pretrained model artifacts, frozen demo dataset | Model does live **inference**, not live training. |
| BI production signal | Lightweight **Looker-ready SQL marts** over canonical/recommendation/audit tables; LookML stubs only if core work is complete | Demonstrates the production reporting path without spending build time on a second UI. |

**No separate Express service.** Next.js already demonstrates the Node/TS side; a second backend purely to name a framework is negative value. Be ready to frame the single-backend choice as deliberate architecture.

---

## 11. Build order — vertical slice that stays runnable

The aim: a working **browser → API → decision → approve** path at every stage. Never a pile of disconnected modules.

- **Stage 0 — Golden scenario + synthetic-truth contract** *(do this first; everything is downstream of it)*. Define the canonical schema, deterministic API-envelope-shaped data generator (known adstock–Hill processes per segment, injected data defects, label-maturity rules, pacing signals, and the inventory-risk SKU), and **locked business invariants with tolerance ranges** — not one exact optimizer dollar allocation.
- **Stage 1 — Thin end-to-end shell:** one Next.js page → one FastAPI endpoint → one static canonical dataset → one fixed recommendation → approve/reject. The seam works before real modeling.
- **Stage 2 — Real ingestion:** Meta `data/paging` JSON + Google nested `results` JSON adapters, validation, canonical schema, SKU resolution, data-quality flags (replace the fixture data). Reuse pre-existing connectors only if they are tested and cheaper than rebuilding; otherwise keep the committed two-platform scope.
- **Stage 3 — Real engine:** simple forecast baselines → label-mature XGBoost BAU forecast with gap-aware validation → chronological cross-fitted controls → jointly estimated residualized response curves → SLSQP + feasibility handling → required constraints (replace the fixed recommendation).
- **Stage 4 — Trust & business controls:** quantile intervals and crossing diagnostics, calibration registry + sensitivity view, approval/audit, inventory restriction, reserve modes, lightweight Looker-ready SQL marts.
- **Stage 5 — Bounded LLM:** SKU ranking + grounded narration (+ optional NL constraints). Only after the deterministic system works.
- **Stage 6 — Harden:** seeded demo button, pretrained artifacts, no mandatory internet, deterministic fallbacks, one-command start, deployed backup, smoke test, frozen dataset, **PDF deck backup**, rehearse 15 min ×2.

---

## 12. The golden synthetic scenario (design this carefully)

Encode these tensions deterministically so the demo tells itself:
- **Meta retargeting** looks strong on *platform* ROAS but is **saturated** (low marginal), with a planted over-attribution signal.
- **Google nonbrand** has genuine **room to scale** (high marginal, in-support) and a small number of deliberately immature/missing conversion labels.
- One **prospecting** campaign repeatedly reaches its budget cap early in the day and must stay funded (NC-CPA / prospecting-floor binding).
- One Google Shopping/PMax campaign shows attractive marginal economics and frequent noon cap-outs, but one promoted **SKU has inventory risk** that blocks part of the otherwise-attractive scale-up.
- Google brand search shows high average ROAS but low utilization and saturation, reinforcing why average ROAS is not enough.
- The optimizer result **lifts blended ROAS visibly** while every constraint holds — and the within-±20% moves still produce a **persuasive headline number** (tune the fixture so the *safe* move is also the *convincing* one).

**Deliberately inserted data defects (shown live, not just claimed):** Meta and Google use different API envelope/nesting conventions; Google `cost_micros` requires normalization; duplicate Meta row; missing Google extraction date (**flagged, not imputed** — could be zero or a failed pull); unknown platform product ID (quarantined); a similar-but-wrong SKU candidate; null new-customer value (imputed + low-confidence); deliberately immature conversion labels; attribution-window mismatch; platform revenue > Shopify DTC revenue; a campaign with inconsistent date coverage.

**Canonical tables:** `fact_ad_performance`, `dim_campaign`, `dim_sku`, `sku_alias`, `fact_commerce_truth`, `fact_inventory_snapshot`, `data_quality_issue`, `calibration_registry`, `model_run`, `model_evaluation`, `recommendation`, `approval`, `execution_event`.

---

## 13. Tests that matter

- Platform-envelope schemas reject malformed nesting and invalid money fields; Google `cost_micros` normalizes correctly.
- Duplicate platform rows don't double-count revenue.
- Unapproved SKU matches are never auto-included.
- Label-maturity policy excludes or flags incomplete 7-day outcomes.
- Chronological folds and the 7-day gap prevent overlapping-label leakage; residuals are produced out of fold.
- The learned BAU model is compared against trailing-14-day and same-weekday baselines; if it does not add value, the safe baseline fallback is used.
- Quantile crossing rate is measured; any final monotone rearrangement is logged as a safety guard.
- Joint response fitting does not let every correlated channel independently claim the same residual outcome.
- Total budget (incl. reserve) is preserved exactly.
- Every optimizer constraint is satisfied; prospecting minimum cannot be violated.
- **Infeasibility test:** contradictory constraints produce an explicit conflict report, never an invalid allocation.
- Stockout-risk SKUs cannot receive increases.
- Recommendations are deterministic for the same model + inputs.
- A rejected recommendation cannot execute; approval is idempotent.
- LLM output cannot modify numeric recommendation fields.
- **Saturation test:** increase budget on a saturated campaign → marginal ROAS falls and the optimizer stops allocating there.
- **Extrapolation test:** a recommendation outside historical support is capped or flagged.
- Golden-scenario tests assert **business invariants and tolerance ranges**, not one exact allocation: Meta retargeting decreases, Google nonbrand increases, inventory blocks unsafe scale, ROAS/NC-CPA/prospecting constraints hold, Conservative is no more aggressive than Expected, and efficiency-first may use reserve.
- Full seeded scenario runs as a smoke test.

---

## 14. 15-minute walkthrough

1. **0:00–1:00 — Scope.** "Narrow cross-platform decision loop; two API-shaped mock exports; four real products; synthetic data; live constrained optimizer. Execution stubbed; pipeline/forecast/allocation/approval/audit are real."
2. **1:00–4:00 — Ingestion & reconciliation.** Run ingest; show row counts, mismatched SKU IDs, approve one suggested mapping, one quarantined ID, attribution & missing-data flags, the canonical table.
3. **4:00–7:00 — Forecasting.** One SKU; Meta vs Google 7-day forecast; compare XGBoost with trailing-14-day and same-weekday baselines; P10/P50/P90; walk-forward error + interval coverage; note label maturity; show response curves differ; point to saturation + historical support.
4. **7:00–11:00 — Allocation.** Current budget + constraints; run optimizer; current vs recommended; **marginal ROAS**; blended ROAS / CM-ROAS / NC-CPA / utilization. **Tighten NC-CPA $45→$40, rerun, explain the trade-off.** Then flip to efficiency-first and show budget move into **reserve**.
5. **11:00–13:00 — Approval & execution.** Open a recommendation; reason codes + uncertainty; adjust/approve; generate **stubbed** Meta/Google payloads; show audit log.
6. **13:00–14:00 — Buyer view.** Switch to planner view; one stockout-risk SKU; media cap + reorder suggestion.
7. **14:00–15:00 — AI workflow & code.** Repo structure; `AI_WORKFLOW.md`; one prompt used; **one suggestion rejected** ("the coding model put business reasoning inside the LLM; I moved all numeric decisions into deterministic services"); tests passing.

---

## 15. Slides (3–5; compression, not screenshots)

1. **The decision problem.** Fragmented platform data → conflicting attribution → uncertain marginal returns → disconnected budget decisions → margin/inventory risk. Objective: maximize incremental contribution while holding ROAS, NC-CPA, prospecting, pacing, inventory guardrails.
2. **System architecture** with **trust boundaries marked:** *models predict · optimizer decides within constraints · LLM explains · human approves · adapters execute.*
3. **Decision logic & trade-offs.** XGBoost quantile BAU + residualized adstock–Hill response + SLSQP; P10/P50/P90; incrementality calibration; contribution economics; inventory guardrail. **Three explicit trade-offs:** predictive-not-causal · narrow two-platform · human approval before execution.
4. **What shipped & the production path.** Shipped: 2-platform API-shaped ingestion, reconciliation, baseline-tested forecast w/ uncertainty, live allocation, approval, execution payload, buyer handoff, audit, and lightweight Looker-ready marts. Next 2 weeks: real Meta/Google auth, Shopify/GA4 ingestion, Triple Whale/Looker integration, **experiment calibration (geo/conversion lift)**, Amazon/Microsoft adapters, drift monitoring, shadow → limited copilot.

---

## 16. Q&A honesty lines (rehearse these)

- *"The synthetic dataset verifies the implementation can recover a known response process. It does **not** prove observational media data identifies causal saturation — production calibration needs incrementality experiments."*
- *"I residualize against controls before fitting the response curve, so it isn't crediting seasonality/promotions to media. On real data, residualization **reduces but doesn't eliminate** confounding — which is exactly why lift tests matter."*
- *"I don't differentiate the tree model; I compare a small **in-support finite difference** to the parametric marginal as a consistency diagnostic, not causal validation."*
- *"ROAS is a **constraint**, not the objective — maximizing a ratio yields pathological low-spend solutions. I optimize risk-adjusted net contribution."*
- *"Execution is a **pluggable adapter** because brands at this scale often already run pacing/activation systems; this focuses on the transparent decision contract."*
- *"I compare XGBoost against simple operational baselines. If it does not beat them on time-aware validation, the system falls back instead of deploying complexity for its own sake."*
- *"If the business constraints are mutually infeasible, the system surfaces the conflict and asks for an explicit relaxation; it never returns an invalid budget plan."*

---

## 17. What we deliberately do **not** build

Full MMM · Prophet · committed Amazon/Microsoft decision-engine integrations · real OAuth · live budget writes · a runtime autonomous agent controlling the workflow · a full replenishment/inventory system · a complex warehouse · full LookML/BI implementation before the core works · ECS/Fargate infrastructure before demo hardening · natural-language-only controls · a chatbot as the main UI · any unverifiable causal-lift claim · visual polish before the optimizer works.

> *A narrow system that demonstrably runs beats a broad architecture with half-working modules. The brief says so directly.*

---

## 18. The settled decision matrix

| Question | Decision |
|---|---|
| Platforms | Meta + Google decision loop; Amazon/Microsoft ingestion only as a zero-risk optional stretch |
| Input format | API-envelope-shaped synthetic JSON, flattened by adapters |
| Frontend | Thin Next.js / TypeScript |
| Backend | FastAPI / Python (no Express service) |
| Data / analytics | DuckDB + pandas |
| Validation | Pandera + Pydantic |
| BAU forecast | XGBoost quantile regression (P10/P50/P90, monotonic, in-support), promoted only against visible simple baselines |
| Forecast validation | Chronological walk-forward splits, 7-day gap, explicit label maturity, quantile-crossing diagnostics |
| Spend-change model | Chronologically cross-fitted residualization + **joint segment-level** adstock–Hill estimation |
| Model connection | Anchored **delta** added to BAU (0 at current spend → no double-count) |
| Seam diagnostic | In-support **finite differences**, not tree derivatives |
| Extrapolation | Bounded (~±20%) and visibly support-aware |
| Optimizer | SciPy SLSQP with explicit pre-solve feasibility/conflict handling |
| Objective | Risk-adjusted net contribution (ROAS/NC-CPA as constraints) |
| Budget handling | Full allocation by default; **explicit reserve** + efficiency-first mode |
| Uncertainty | Bootstrap response params + BAU quantiles (Expected/Conservative fallback) |
| Attribution | Separate dedup / normalization / **calibration registry** w/ provenance |
| Runtime LLM | Bounded leaf functions (SKU ranking, grounded narration, optional confirmed NL constraints); deterministic fallbacks; no orchestration agent |
| Inventory | Thin no-scale guardrail + buyer handoff |
| Execution | Pluggable, stubbed, audited |
| BI production path | Lightweight Looker-ready SQL marts; LookML only after the core works |
| Build method | Vertical slice that stays runnable from Stage 1 |
| Vendor framing | Vendor-neutral, alignment-not-revelation, Moby only in narration/Q&A |

---

*Next artifact: the golden-scenario specification + deterministic API-envelope-shaped synthetic-data generator, with business invariants and tolerance ranges frozen as test fixtures. Every model, chart, optimizer test, and demo beat depends on that scenario being designed well.*

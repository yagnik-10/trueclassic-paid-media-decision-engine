# Slide Deck + Run-of-Show

Presentation plan for the True Classic Paid Media exercise. Slides are
**compression, not screenshots** — the running app is the proof. Every number below
is **verified against the live engine** (defaults, seed `20240117`).

Companion docs: `docs/FINAL_PLAN.md` (§14–16), `docs/CONSTRAINTS.md`,
`docs/AI_WORKFLOW.md`, `docs/PROJECT_REPORT.md`.

---

## 0. Verified demo numbers (single source of truth)

| Fact | Value | Use |
|---|---|---|
| Calibrated blended ROAS | `3.93× → 4.19×` | clears the **4.0×** primary floor with headroom |
| Net contribution / day | `≈ +$17.2K/day` (to ~$130,180) | the objective the optimizer maximizes |
| CM ROAS | `1.82× → 1.94×` | contribution-economics lens (breaks even 1.0×) |
| ROAS floor that trips infeasibility | `4.3×` (short 0.106×; ceiling ≈ `4.19×`) | the **governor** live beat |
| Movement bound for a *visible* reallocation | `±20% → ±30/40%` | the live recompute beat |
| Efficiency-first reserve at defaults | `$0` | **do NOT** promise a positive reserve live |
| Waste-control proof | **PMax inventory no-scale** (live, at defaults) | carries the "holds back when it should" story |
| Forecast interval coverage | `81%` vs `80%` target (XGBoost conformal) | "trust the bands" |

> Restraint story = **PMax inventory hold**, not the reserve line. The reserve is $0 at
> defaults and only goes positive in infeasible settings — showing it would show an
> infeasible plan, strictly worse than $0.

---

## 1. Brief requirements → where each is proven

| Brief requirement | Slide | Live demo moment | In the app |
|---|---|---|---|
| **Per-channel forecasts (Meta vs Google); show how signal & spend-response curves differ** | 3 | Forecast bands (Campaign↔Channel toggle, per-bar logos) → response curves: Nonbrand rising vs Brand/Retargeting saturated | **Forecast & Response** |
| **Confidence intervals / accuracy metrics — how much to trust** | 3 | P10–P90 bands + `81% vs 80%` coverage; WAPE + untouched-test + holdout drift | **Forecast & Response** + **Model Evidence** |
| **Budget allocation across channels under constraints** | 1, 3 | Current vs recommended (movement/channel/objective); run optimizer | **Decision Overview** + **Budget Planner** |
| **Primary: Blended ROAS ≥ 4.0×** | 1, 3 | Hero KPI `3.93→4.19×` clears floor; raise to `4.3×` → infeasible | **Decision Overview**, **Budget Planner** |
| **Secondary: NC-CPA ≤ target** | 3 | NC-CPA guardrail tile; tighten the ceiling, rerun, explain trade-off | **Budget Planner** |
| **Tertiary: ~100% efficient utilization** | 3 | Marginal-ROAS pull-back/scale logic; PMax inventory hold; pacing flags | **Budget Planner**, **Buyer & Inventory** |
| **Governance: human approval, audit, execution** | 2, 4 | Approve → hash-chained ledger → stubbed Meta/Google payloads | **Decision Overview**, **Audit & Business Controls** |
| **AI workflow (tools, prompts, interventions)** | 2, 5 | Bounded LLM narrator (gpt-4o-mini) + the rejected "reasoning-in-LLM" suggestion | repo + `AI_WORKFLOW.md` |

---

## 2. Slides (5 + title)

### Title — one line
**"A vendor-neutral decision & governance layer over Meta + Google media and Shopify
truth."** Subtitle: *Models predict · optimizer decides · LLM explains · human approves
· adapters execute.*

### Slide 1 — The decision problem
- **On slide:** Fragmented platform data → conflicting attribution → uncertain marginal
  returns → disconnected budget decisions → margin/inventory risk. Objective:
  **maximize incremental contribution while holding ROAS, NC-CPA, prospecting, pacing,
  and inventory guardrails.**
- **Notes (45s):** "True Classic already thinks in contribution margin, not platform
  ROAS — this aligns with that. The core idea is **marginal ROAS, not average ROAS**: a
  6× channel can be saturated; a 4× channel can have profitable room. Allocation follows
  the *next dollar*." (Alignment, not revelation.)
- **Proves:** framing of the allocation problem + the three success metrics.

### Slide 2 — System architecture + trust boundaries
- **On slide:** the pipeline diagram with boundaries marked —
  `Meta/Google API-shaped JSON → adapters → canonical → forecast (XGBoost quantile +
  baselines) → residualized response → SLSQP optimizer → human approval → stubbed
  execution → audit ledger`. LLM sits **off** the critical path (explains only).
- **Notes (60s):** "Five roles, five trust boundaries. Models *predict*, the optimizer
  *decides within constraints*, the LLM *explains*, the human *approves*, adapters
  *execute*. Numbers are always deterministic; the LLM never computes, ranks, or executes
  — and every LLM feature has a deterministic fallback."
- **Proves:** governance + AI trust boundary.

### Slide 3 — Decision logic & trade-offs
- **On slide:** XGBoost quantile BAU + residualized adstock–Hill response + SLSQP;
  P10/P50/P90; incrementality calibration; contribution economics; inventory guardrail.
  **Three explicit trade-offs:** predictive-not-causal · narrow two-platform · human
  approval before execution.
- **Notes (60s):** "Forecast differs by channel (signal); the response *curve* differs by
  campaign (spend-response) — that's the M2 ask. The optimizer maximizes risk-adjusted
  net contribution **subject to** the ROAS floor, because maximizing a ratio gives
  pathological low-spend answers."
- **Proves:** per-channel forecasts, confidence/accuracy, constraints.

### Slide 4 — Governance & the decision contract
- **On slide:** the approval flow — recommendation (reason codes + uncertainty) → human
  approve/reject → append-only **hash-chained** ledger → stubbed per-platform payloads.
  Infeasible plans are surfaced, never silently "solved."
- **Notes (40s):** "Nothing executes without a human. The plan is an immutable snapshot;
  approval binds to its `scenario_id`. If constraints are mutually infeasible the system
  shows the conflict and asks for an explicit relaxation."
- **Proves:** governance/approval/audit.

### Slide 5 — What shipped & the production path
- **Shipped:** 2-platform API-shaped ingestion + reconciliation, baseline-tested forecast
  with uncertainty, live constrained allocation, approval, execution payloads, buyer
  handoff, audit ledger, Looker-ready marts, and a bounded LLM narrator.
- **Next 2 weeks:** real Meta/Google auth, Shopify/GA4 ingestion, Triple Whale/Looker,
  **experiment calibration (geo/conversion lift)**, **Amazon/Microsoft adapters**, drift
  monitoring, shadow → limited copilot.
- **Notes (30s):** "Amazon is the next adapter, not a redesign — I kept the live system
  narrow and runnable."

---

## 3. Run-of-show (live demo, ~10–12 min)

**Pre-flight:** API up on `:8000`, web on `:3000`, ledger reset to a clean **pending**
state, start on **Decision Overview**. (LLM narration works either way — live
`gpt-4o-mini` or deterministic fallback.)

1. **Scope (0:00–0:45).** "Narrow cross-platform decision loop; two API-shaped exports;
   synthetic data; live constrained optimizer. Execution stubbed; pipeline / forecast /
   allocation / approval / audit are real."

2. **Decision Overview (0:45–3:00).** Lead with the hero KPIs: **blended ROAS
   `3.93→4.19×` clears the 4.0× floor**, **net contribution `+$17.2K/day`**, CM ROAS as
   the optimization lens. Read the **AI narration** (badge shows gpt-4o-mini) — note it's
   prose-only; every number renders from app state. Walk the **Current vs Recommended**
   movement bars (logos per row): scale Nonbrand/Shopping/Broad Prospecting, trim
   Brand/Retargeting/Advantage+, PMax **HELD**.

3. **Forecast & Response (3:00–5:30).** Forecast bands per campaign (logos make
   Google/Meta explicit); flip the **Channel** toggle to show the per-channel rollup;
   point to **81% vs 80% coverage**. Then the payload: open the **response curves** —
   **Nonbrand Search rising** (room to scale) vs **Brand Search / Dynamic Retargeting
   saturated/declining** (trim). "Allocation follows marginal response, not total
   forecast size." (Mention: bars are 7-day; the curve is per-day.)

4. **Model Evidence (5:30–7:00).** Overall **WAPE** + "≈X% accuracy"; the
   untouched-test forecast-vs-actual and actual-vs-predicted; the **PMax holdout-drift**
   retrain signal — "promoted on pre-test, regressed on the untouched test; flagged, not
   silently switched, because that would leak the test set into selection."

5. **Budget Planner — the governor (7:00–9:30).** Two beats:
   - **Visible reallocation:** raise **movement bound ±20% → ±40%**, recompute, show the
     bigger dollar moves.
   - **The governor:** raise **ROAS floor 4.0× → 4.3×**, recompute → **infeasible**, with
     the exact conflict (`4.194× < 4.30×, short 0.106×`) and the plan banned from
     approval. "It tells me it can't hit the target instead of returning a worse plan."
   - (Optional) tighten **NC-CPA** and explain the prospecting/retargeting trade-off.
   - **Restraint:** lean on **PMax inventory no-scale** (live at defaults) — *not* the
     reserve line (which is correctly $0).

6. **Approval & audit (9:30–11:00).** Reset floor to 4.0× (feasible), **Approve** →
   status flips, **execution preview** renders stubbed Meta/Google set-budget payloads,
   the **append-only hash-chained ledger** appends, button disables. Peek at **Audit &
   Business Controls** for the chain integrity.

7. **AI workflow (11:00–12:00).** "Build-time AI = Claude Code / Cursor. Runtime narrator
   = bounded LLM sidecar, gpt-4o-mini here, deterministic fallback. **One suggestion I
   rejected: the coding model put business reasoning inside the LLM — I moved all numeric
   decisions into deterministic services.**" Tests green; determinism fingerprinted.

---

## 4. Q&A honesty lines (rehearse)

- "The synthetic dataset proves the implementation can **recover a known response
  process** — it does not prove observational data identifies causal saturation;
  production needs lift experiments."
- "ROAS is a **constraint, not the objective** — maximizing a ratio yields pathological
  low-spend solutions; I optimize risk-adjusted net contribution."
- "I residualize against controls before fitting the response curve, so it isn't
  crediting seasonality/promos to media — residualization **reduces but doesn't
  eliminate** confounding."
- "Marginal ROAS uses an **in-support finite difference** vs the parametric marginal as a
  consistency diagnostic, not causal validation."
- "If constraints are mutually infeasible, the system **surfaces the conflict** and asks
  for an explicit relaxation — it never returns an invalid budget plan."
- **Allocation precision (the honest one):** "On realistic, noisy data the plan is
  **direction-recovered with guardrails, not a dollar guarantee** — Model Evidence flags
  decision-use **amber** because the allocation direction isn't stable under ±20% marginal
  error. That's exactly why a human approves before anything executes. The forecast,
  intervals, and governance are demo-solid; the allocation is recovered direction plus
  guardrails, not gospel."
- "Same number, two lenses: **gross** marginal ROAS against the gross break-even,
  **contribution-margin** ROAS against 1.0×, related by the campaign's margin rate."
- **Amazon:** "Meta + Google end-to-end; Amazon is the next **adapter**, not a redesign —
  I kept the live system narrow and runnable."
- **Runtime model:** "Runtime narration is a bounded LLM sidecar; in this demo it's
  served by **gpt-4o-mini**, with a deterministic template fallback. The LLM never
  computes budgets, approves, or executes."
- **SKU reconciliation scope (why no Reject / SKU picker):** "Reconciliation is
  intentionally minimal — high-confidence IDs auto-resolve, plausible low-confidence
  ones need human approval, and truly unmapped IDs are quarantined for manual review;
  until approved, nothing enters attribution or optimization. SKU mapping is upstream
  data hygiene, so it's a lightweight governance overlay — the durable, hash-chained
  audit ledger is reserved for the budget decisions that actually move money. In
  production I'd add reject, alternate-SKU selection, and evidence review, but I kept
  the live path narrow and governed."
- **Why 0% rows aren't one-click-approvable:** "A quarantined 0%-confidence row has no
  concrete suggested SKU — its nearest-string candidates are hints for manual review,
  not an auto-bind target — so the system never offers a confident one-click approve
  to an arbitrary SKU."

---

## 5. Don'ts
- Don't promise a positive **reserve** live (it's $0 at defaults — correct restraint).
- Don't claim **causal** identification from synthetic/observational data.
- Don't say the runtime narrator is **Claude** (it's gpt-4o-mini in this demo).
- Don't add **Amazon** labels/claims — it isn't implemented.
- Don't let displayed numbers come from LLM prose — they're always from app state.

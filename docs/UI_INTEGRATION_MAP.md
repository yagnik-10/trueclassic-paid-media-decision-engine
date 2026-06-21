# UI Integration Map — the Vite prototype → Next.js `frontend/` + FastAPI

**Decision:** one production frontend = the existing Next.js `frontend/`. The Vite
app (`true-classic/`) is a **design/component source only** — never independently wired to
the backend. Port the visual shell into `frontend/`; replace every mock object/action with
the real contract below.

## Live API surface (verified in `backend/api/main.py`)
| Route | Returns | Use |
|---|---|---|
| `GET /api/recommendation?policy=&<constraints>` | `Recommendation` | the plan: `kpis`, `lines[]`, `binding`, `constraints`, `interval_calibration` |
| `POST /api/recommendation/{scenario_id}/decision` | `DecisionResponse` | approve / reject → append-only ledger; `execution_events[].is_stub=true` |
| `GET /api/recommendation/{scenario_id}/audit` | `DecisionResponse` | stored snapshot for a scenario |
| `GET /api/audit/log` | `DecisionResponse[]` | scenario history timeline |
| `GET /api/audit/verify` | `AuditChainStatus` | hash-chain integrity (`ok`, `head_hash`, `broken_seq`) |
| `GET /api/ingestion` | `IngestionSummary` | `feeds[]`, `dq_issues[]`, `sku_resolutions[]` |
| `POST /api/sku-resolution/{id}/approve` | `SkuResolutionItem` | resolve quarantined SKU |
| `GET /api/calibration/registry` | `CalibrationRegistryResponse` | calibration entries + provenance |
| `GET /api/marts`, `GET /api/marts/{name}` | mart rows | Looker-ready marts over the ledger |
| `GET /api/health` | status | liveness |

## View / control → backend source
### 1. Decision Overview (`DecisionOverview.tsx`)
- KPI cards → `recommendation.kpis`: **primary** `cm_roas_current/projected`,
  `net_contribution_current/projected`; **secondary** `blended_roas_*` (calibrated gross,
  the governance floor lens), `reported_roas_*` (platform-reported), `reserve`, `nc_cpa_projected`.
- Current vs Recommended bars → `lines[].current_spend` / `recommended_spend` / `delta_pct`.
- Reserve card → `kpis.reserve` (not a client subtraction).
- Strategy cards / warning tooltips → `lines[].pacing_flag`, `reason_codes`, `risk_flags`,
  `marginal_roas` vs `marginal_roas_downside`, `marginal_hurdle`.
- "Apply Strategy" → `POST .../decision` (`approve`). Copy: *recorded to ledger; execution stubbed.*

### 2. Forecast & Response (`ForecastResponse.tsx`)
- Curve + band → `lines[].forecast_p10/p50/p90` (**80%** deployed interval; not 95%),
  `forecast_p10_raw/p90_raw`, `forecast_model`.
- Response shape → `response_slope`, `response_quad`, `marginal_roas(_downside)`.
- Channel selector → iterate `lines[]` (Meta + Google only).

### 3. Budget Planner (`BudgetPlanner.tsx`)
- Sliders → `ConstraintParams`: `roas_floor`, `nc_cpa_target`, `prospecting_min_share`,
  `movement_bound` (the "±20% daily movement"), `reserve_mode` (`growth` | `efficiency_first`).
- Recalculate → `GET /api/recommendation` with those params.
- Compare baseline vs optimum → `lines[].current_spend` vs `recommended_spend`; `kpis` current vs projected.
- Policy expected/conservative → `policy` query param.

### 4. Audit Controls (`AuditControls.tsx`)
- Scenario history → `GET /api/audit/log`; integrity badge → `GET /api/audit/verify`.
- Calibration table + override → `GET /api/calibration/registry`; overrides applied via
  `calibration_overrides` on the recommendation call; provenance in `recommendation.calibration_registry`.
- Event log expansions → `DecisionResponse` fields (`payload_hash`, `execution_events`, status).

### 5. Data Unification (`DataUnification.tsx`)
- Source health cards → `IngestionSummary.feeds[]` (`raw`/`normalized`/`quarantined`).
- DQ ledger → `dq_issues[]`; SKU resolution table + approve → `sku_resolutions[]` + `POST .../approve`.

### 6. New Optimization modal (`NewOptimizationModal.tsx`)
- Inputs → `ConstraintParams` + `policy`; submit → `GET /api/recommendation`.

### 7. Header / Sidebar
- Scenario status badge → `recommendation.status` + audit verify; "New Optimization" opens modal.

## Controls with NO backend support — remove or label "future / illustrative"
- **TikTok / YouTube** campaigns + calibration rows — out of scope (Meta + Google only).
- **GenAI-computed** numbers — LLM is Stage 5; allowed only to narrate validated output with a deterministic fallback.
- **Automated pace rules** ("pause if ROAS < 2.0x over 48h") — no runtime orchestration (hard rule); advisory only.
- **Rollback / delete** — ledger is append-only; a reversal is a new compensating decision, not a delete.
- **Planning horizon 7/14/30 recalculation** — engine is daily steady-state; derive client-side display only, or label.
- **What-if CPM +15% / conv-drop shocks** — partial: approximate via `policy=conservative` + `calibration_overrides`; a true CPM shock knob does not exist.
- **Transaction-level reconstruction table** — closest real data is `dq_issues` + `sku_resolutions`; no per-transaction endpoint.
- **Inventory days-cover table** — no dedicated endpoint today (inventory enters only via pacing flags).

## Gaps to close for a truthful "decision-safety" banner
The model-quality verdict (`safe_for_model_demo`, `safe_for_decision_demo`, WAPE, interval
coverage, holdout drift, direction stability) is **not** on the API — it lives in
`reports/model_performance/metrics.json`. Options:
- **(preferred)** add read-only `GET /api/model-health` serving the non-leaky subset → banner is live, not hardcoded.
- Per-scenario safety derives from `recommendation`: `feasible`, `conflicts`,
  `binding.solver.{business_feasible,solver_converged,candidate_stable,solver_qualified}`,
  `is_sensitivity_override`, `risk_flags`.

## Port order (runnable after each step)
1. Decision Overview → 2. Campaign allocation table → 3. Constraints/recalculation →
4. Forecast/response charts → 5. Approval/reject → 6. Audit trail → 7. Ingestion/data health.

## Port stack notes
- Add **Tailwind v4 + lucide-react** to `frontend/` (the prototype is Tailwind-heavy) — or translate classes.
- Keep **recharts** for charts (already wired + tested); restyle to match the prototype rather than porting raw SVG.
- Do **not** copy: mock state ownership, fake responses, local approval state, an unused GenAI scaffolding, unsupported platforms.

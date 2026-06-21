# Constraints & Outputs — Budget Planner

What a marketer can change in **Budget Planner → Constraints & Allocation**, what
values are realistic vs. not, and what the engine returns. All controls are
**deterministic inputs to the SciPy SLSQP optimizer** — the LLM never touches them.

Source of truth:
- Validation bounds: `backend/api/schemas.py` (`ConstraintParams`)
- Policy defaults: `backend/decision_engine/config.py`
- Solver behaviour: `backend/decision_engine/engine/optimizer.py`, `recommend.py`
- UI controls: `frontend/src/components/BudgetPlanner.tsx`

Editing any control produces a **new `scenario_id`** (a deterministic content hash of
policy + constraints + data + config). Approval binds to that exact snapshot.

---

## 1. Adjustable controls

| Control | Default | Validated range (422 outside) | Realistic range | Effect |
|---|---|---|---|---|
| **Calibrated ROAS floor** (`roas_floor`) | `4.0×` | `1.0 – 10.0` | `3.5 – 4.2×` | Hard portfolio floor on calibrated blended ROAS. The brief's primary success metric. |
| **NC-CPA ceiling** (`nc_cpa_target`) | `$45` | `5 – 200` | `$35 – $60` | Max new-customer acquisition cost. |
| **Prospecting floor** (`prospecting_min_share`) | `0.30` (realistic) / `0.33` (golden) | `0.0 – 0.80` | `0.25 – 0.45` | Min share of spend on prospecting/acquisition (anti-retargeting-only). |
| **Movement bound** (`movement_bound`) | `0.20` (±20%) | `0.05 – 0.40` | `0.15 – 0.30` | Max ± change to any campaign's budget in one cycle. Conservative policy shrinks the *effective* bound to 75%. |
| **Policy mode** (`policy`) | `expected` | `expected` \| `conservative` | — | `expected` = point-estimate marginals; `conservative` = downside (P10-ish) marginals **and** ±movement × 0.75. |
| **Reserve mode** (`reserve_mode`) | `growth` | `growth` \| `efficiency_first` | — | `growth` deploys the full budget; `efficiency_first` may withhold a reserve line when no campaign clears its hurdle. |
| **Calibration overrides** (`calibration_overrides`) | none | per-segment coefficient | what-if only | Sensitivity what-ifs. **Marks the plan `is_sensitivity_override=True` → never approvable/executable.** |

Two thresholds are **derived, not user-editable** (governance invariants):
- **Contribution break-even** = `1.0×` CM ROAS.
- **Marginal CM hurdle** = `HARD_FLOOR_SAFETY = 1.05×` (break-even × safety cushion).
  Campaigns whose marginal CM ROAS is below this are not scaled.

---

## 2. Realistic vs. non-realistic values (and what happens)

### `roas_floor` — calibrated ROAS floor
- **Realistic (`3.5–4.2×`):** binds meaningfully. At the default `4.0×` the plan
  clears it with headroom (≈`4.19×` projected) — feasible and approvable.
- **Ceiling ≈ `4.19×`:** the best ±20% reallocation tops out near `4.19×` projected,
  so **any floor above ~`4.2×` is infeasible** (verified: `4.3×` is already short by
  `0.106×`; `5.0×` short by `0.807×`). Output: `feasible=false`, the floor appears in
  `conflicts` with its exact shortfall, and the allocation becomes a **diagnostic
  candidate** (not approvable). This is the cleanest way to *demonstrate* the governor.
- **Too low (`< ~2×`):** trivially satisfied — slack, no governance signal. Allowed,
  just uninteresting.
- **Outside `1.0–10.0`:** rejected with HTTP **422** before the solver runs.

### `nc_cpa_target` — new-customer CPA ceiling
- **Realistic (`$35–$60`):** a live ceiling; can bind on retargeting-heavy mixes.
- **Too low (`< ~$25`):** often **infeasible** — appears in `conflicts`.
- **Too high (`> ~$120`):** non-binding (slack).
- **Outside `5–200`:** **422**.

### `prospecting_min_share` — prospecting floor
- **Realistic (`0.25–0.45`):** enforces a healthy acquisition mix; can become the
  *binding* constraint that explains why a low-marginal prospecting campaign is held
  (reason `strategic_floor`, not waste).
- **Too high (`> ~0.6`):** forces budget into prospecting past its marginal returns →
  pushes the ROAS floor toward **infeasible**, or yields a feasible-but-worse plan.
- **`0.0`:** floor off — optimizer free to drop prospecting entirely.
- **Outside `0.0–0.80`:** **422**.

### `movement_bound` — max change per campaign
- **Realistic (`0.15–0.30`):** a believable single-cycle reallocation. The live demo
  recompute uses ±20% → ±30/40% to make the allocation visibly shift.
- **Tight (`0.05`):** very little can move; deltas look limp; floor may stay unmet
  simply because the optimizer can't reach it.
- **Loose (`0.40`):** aggressive but allowed — larger reallocations, larger KPI swing.
- **Outside `0.05–0.40`:** **422**.

### `policy` mode
- **`expected`:** uses point-estimate marginals (the headline plan).
- **`conservative`:** uses downside marginals **and** shrinks movement to 75%
  (`effective_movement_bound`). More cautious, smaller swings; a campaign near its
  hurdle on the downside estimate won't be scaled.

### `reserve_mode`
- **`growth` (default):** deploys the full budget whenever feasible — `reserve = 0`.
  Clearest reallocation story.
- **`efficiency_first`:** the optimizer may **hold money in reserve** when the next
  dollar can't clear its contribution hurdle (the waste-control story). At current
  demo settings the reserve is typically `$0` (no campaign is below-hurdle with
  spare budget) — that is *correct restraint*, not a bug.

### `calibration_overrides`
- A **what-if** that swaps a segment's calibration coefficient. The plan is flagged
  `is_sensitivity_override=True` and an amber "Sensitivity · not registry-approved"
  badge appears. It is intentionally **not approvable** (can't leak an unapproved
  coefficient into the audit ledger).

---

## 3. What the output is

Every recompute returns one **`Recommendation`** (`GET /api/recommendation`). The key
fields the UI renders:

### Top-level status
- **`feasible`** — `true`/`false`. The single most important flag.
- **`conflicts[]`** — when infeasible, the **unmet soft constraints with exact
  shortfalls** (e.g. `"blended_roas_floor: 3.71× < 4.50× (short 0.79×)"`). Hard bounds
  (movement, caps, inventory, marginal floor) are enforced directly and never appear here.
- **`scenario_id`**, **`effective_movement_bound`**, **`is_sensitivity_override`**.

### Per-campaign allocation — `lines[]`
For each campaign: `current_spend → recommended_spend`, `delta_pct`,
`marginal_cm_roas` (+ downside), local response curve params, forecast band
(`p10/p50/p90`), `pacing_flag` (`scale_opportunity` / `capped_constrained` /
`strategic_floor` / `pullback_candidate` / `waste_risk` / `healthy`),
`reason_codes`, and `risk_flags` (e.g. `inventory_no_scale`).

### Portfolio KPIs — `kpis`
- `blended_roas_current → projected` (the **enforced** calibrated floor lens)
- `cm_roas_current → projected` and `net_contribution_current → projected` (the
  **objective** the optimizer maximizes)
- `reported_roas_*` (platform-reported context — the over-attribution gap)
- `total_current_spend → total_recommended_spend`, `reserve`, `nc_cpa_projected`

### "Why this plan" — `binding`
- **`portfolio[]`** — each constraint tagged `binding` (satisfied at the margin) /
  `slack` / `violated`, with human-readable detail.
- **`per_campaign[]`** — which hard bound pins each campaign (movement cap / daily
  cap / inventory / below-hurdle).
- **`solver`** — SLSQP terminal status, multi-start stability, feasibility decomposed
  from convergence/optimality (advisory only; **execution always needs human approval**).

---

## 4. Two example outcomes

**Feasible (defaults: 4.0× / $45 / 0.30 / ±20% / growth / expected)**
- `feasible=true`; blended ROAS `3.93× → 4.19×` (clears the `4.0×` floor);
  net contribution rises ≈ `+$17.2K/day`; full budget deployed (`reserve=0`).
- Top scale-ups: Google Nonbrand Search, Google Shopping, Meta Broad Prospecting;
  trims: Brand Search, Dynamic Retargeting, Advantage+ Shopping.
- **Approvable** — Approve writes to the append-only hash-chained ledger and renders
  the stubbed execution payloads.

**Infeasible (e.g. raise `roas_floor` to `4.3×`)**
- `feasible=false`; `conflicts = ["calibrated blended ROAS 4.194× < floor 4.30×
  (short 0.106×)"]`.
- The allocation shown is a **diagnostic candidate** (clipped solver iterate), clearly
  banned from approval. This is honest governance — the engine reports it can't hit the
  target rather than quietly returning a worse plan.

---

> All ranges above are deterministic and reproducible (fixed seed `20240117`,
> `n_jobs=1`). Changing a `config.py` default is a scenario change and must update the
> fingerprint test + `docs/DECISIONS.md`.

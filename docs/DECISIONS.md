# Decision log

Architectural decisions and any deviations from [FINAL_PLAN.md](FINAL_PLAN.md).
Per the operating rules, the FINAL_PLAN architecture is canonical — it is not
replaced with a simpler or broader alternative without recording the change, its
rationale, risks, and impact here first.

---

## D-001 — Canonical plan relocated to `docs/FINAL_PLAN.md`
**Stage 0.** The plan was delivered at the repo root as
`TrueClassic_Paid_Media_Decision_Engine_FINAL_PLAN.md`; the operating rules
reference `docs/FINAL_PLAN.md`. **Decision:** move it into `docs/` unchanged.
**Risk:** none (content identical). **Impact:** scaffolding only.

## D-002 — Generator forward-simulates a *known* adstock–Hill process
**Stage 0.** FINAL_PLAN §12 requires the generator to encode "known adstock–Hill
processes per segment"; the operating rules forbid *implementing* Hill **fitting**
in Stage 0. **Decision:** the generator forward-simulates from analytic Hill
curves (the ground truth a Stage-3 model will later try to recover). No curve
fitting, optimization, or learned model exists in Stage 0. **Risk:** confusion
between "truth process" and "fitted model" — mitigated by docstrings in
`synth/scenario.py` and this entry. **Impact:** none to architecture.

## D-003 — Python 3.13 venv (not 3.14)
**Stage 0.** The machine defaults to Python 3.14, which lacks wheels for parts of
the pinned stack. **Decision:** target 3.11–3.13; the Makefile uses `python3.13`.
**Risk:** contributor must have 3.13. **Impact:** `requires-python = ">=3.11,<3.14"`.

## D-004 — `pandera.pandas` import path
**Stage 0.** Pandera ≥0.20 moved the pandas backend to `pandera.pandas`.
**Decision:** import `pandera.pandas as pa`. **Impact:** schemas only.

## D-005 — Two SKU-resolution defects are distinct
**Stage 0.** The defect list separates "one likely SKU candidate requiring
approval" from "one unknown SKU requiring quarantine". **Decision:** model them
as two separate `sku_alias` rows / defect types (`sku_candidate_needs_approval`,
`unknown_sku_quarantine`), giving 11 total defect classes. **Impact:** defect
catalog and tests.

## D-006 — Operational tables defined now, populated later
**Stage 0.** `model_run`, `model_evaluation`, `recommendation`, `approval`,
`execution_event` have no rows until Stages 3–5. **Decision:** define their
Pandera schemas in Stage 0 and emit typed **empty** frames (with `coerce=True` so
empty frames still validate). **Risk:** none. **Impact:** schema module.

## D-007 — Decision hurdles are economically DERIVED (supersedes the `2.8` constant)
> **Status: PARTIALLY SUPERSEDED BY D-020.** The **hard scale floor**
> (break-even × `HARD_FLOOR_SAFETY`) remains ACTIVE — it characterizes the
> scenario's latent truth. The **efficiency-first hurdle, per-campaign hurdles,
> and reserve-feasibility policy** (incl. `EFFICIENCY_SAFETY`,
> `campaign_efficiency_hurdle`, `efficiency_reserve_feasible`) were **removed from
> active Stage 0 scope; reconsider during Stage 3/4.** The reserve content below is
> retained as the later-stage spec.

**Stage 0 (revised after Codex review).** The marginal-ROAS hurdles are no longer
magic numbers. They are derived in `backend/decision_engine/economics.py`:
- marginal **break-even ROAS** = `1 / weighted_contribution_margin` (the next
  dollar covers itself out of margin). For the locked mix the weighted margin is
  **0.581 → break-even 1.722**.
- **hard scale floor** = break-even × `HARD_FLOOR_SAFETY (1.05)` = **1.807**.
- **efficiency-first hurdle** = break-even × `EFFICIENCY_SAFETY (1.60)` = **2.754**.

Only the two safety multipliers remain policy knobs in `config.py`, with the
rationale documented there. The efficiency-first reserve **emerges** from this
hurdle (freed sub-hurdle budget exceeds super-hurdle absorptive capacity); it is
not a number chosen to force reserve usage. The earlier hand-picked `2.8` was
*validated* by this derivation (2.754 ≈ 2.8) — it was defensible but undocumented.
`test_economics.py` proves the hurdle moves with margin and with risk policy.
**Risk:** safety multipliers are still judgment calls; documented and tested.

**Revision 2 (second Codex review): hurdles are now campaign/SKU-mix-specific.**
> _Status: SUPERSEDED BY D-020 — the efficiency hurdles and reserve-feasibility
> policy described here were removed from Stage 0; reconsider during Stage 3/4._

The portfolio-weighted values above are kept as an explicitly-documented
*fallback*; the preferred policy uses per-campaign hurdles
(`campaign_break_even` / `campaign_hard_floor` / `campaign_efficiency_hurdle` =
`1/campaign_margin × safety`). `efficiency_reserve_feasible()` evaluates each
campaign against its own hurdle by default. A lower-margin campaign therefore
carries a *higher* hurdle (e.g. the 0.548-margin prospecting/brand campaigns →
efficiency hurdle 2.92 vs 2.61 for the 0.614-margin ADV/Shopping). Reserve
feasibility now follows these derived per-campaign hurdles, not a global constant.

## D-008 — Blended ROAS starts in a band below target; no knife-edge crossing
> **Status: PARTIALLY SUPERSEDED BY D-020.** The **scenario-design facts** remain
> ACTIVE and tested: calibrated blended ROAS starts below the 4.0 target with a
> clear platform-vs-calibrated over-attribution gap. The **bounded-reallocation
> result and the constrained allocation witness/search** (`tests/_feasibility.py`,
> the `≥4.10`/`≥4.05` candidate ROAS) were **removed from active Stage 0 scope;
> reconsider during Stage 3.** Stage 0 now asserts only that the scenario
> *supports* a future feasible optimization, never a computed allocation.

**Stage 0 (revised after Codex review).** The earlier fixture sat at ~3.946 →
~4.034 — a crossing so tight it looked manufactured. **Decision:** retune the
data-generating assumptions (not the recommendation) so the result emerges from a
broad band:
- current **calibrated** blended ROAS ≈ **3.88** (asserted in **[3.75, 3.95]**),
  comfortably below the 4.0 primary-metric floor (the problem state);
- a bounded ±20% reallocation reaches ≈ **4.12** (asserted **≥ 4.10**), clearing
  the floor with headroom; improvement ≈ **0.23** (asserted **≥ 0.15**); net
  contribution also improves;
- **platform-reported** blended ROAS ≈ **5.9** (the over-attribution gap; the
  calibrated number is the decision basis — the thesis is "optimize business
  outcomes, not platform ROAS").

The lift mechanism is structural: the saturated channels (retargeting, brand)
carry more budget at very low incrementality (high platform ROAS, low marginal),
and Google nonbrand has deep pre-saturation headroom (high marginal), so freed
budget redeploys at a large ROAS spread. No final allocation is hardcoded; tests
assert ranges, leaving the Stage-3 optimizer room to solve. **Impact:** scenario
params in `scenario.py`; `test_business_invariants.py`.

**Revision 2 (second Codex review): the feasibility proof is now CONSTRAINT-VALID.**
> _Status: SUPERSEDED BY D-020 — the constrained allocation witness/search
> (`tests/_feasibility.py`) was removed from Stage 0; reconsider during Stage 3.
> The historical record below is retained for that stage._

The earlier `≥4.10` claim came from a greedy marginal-rank helper that *ignored
constraints* — it scaled the inventory-constrained PMax (+11%) and pushed
prospecting share to 0.321 (below the 0.35 floor) to reach an infeasible 4.1146.
That witness is removed. The Stage-0 feasibility proof is now a transparent
test-only constrained enumeration (`tests/_feasibility.py`) that respects ±20%
movement, daily caps, the inventory no-scale rule, the prospecting-share floor,
budget accounting (reserve ≥ 0), the ROAS floor, and positive contribution lift.
The actual constraint-valid witness:
- current calibrated blended ROAS ≈ **3.884**;
- witness calibrated blended ROAS ≈ **4.099** (asserted **≥ 4.05**);
- contribution lift ≈ **+2 654** (asserted **> 0**);
- prospecting share ≈ **0.351** (≥ 0.35); PMax **not** scaled up; all moves within
  ±20%; total spend ≈ **21 680** of **21 800** budget (reserve ≈ 120).

This is proof the feasible region is non-empty — **not** the expected Stage-3
SLSQP allocation, and runtime/model code never imports the search.

## D-009 — Latent generator truth is isolated from the model-input path
**Stage 0 (Codex blocking fix 1).** `scenario_truth` (marginal ROAS,
incrementality, noise, capacity-to-floor) is **latent generator truth** and a
target-leakage risk. **Decision:** keep it in memory on the `Dataset` object for
tests; never write it to `data/canonical` or `data/raw`. Persisting it requires
an explicit `--write-latent-truth` opt-in and goes only to
`data/internal/latent/scenario_truth.json` (gitignored). The normal
`make generate` path does not emit it. `test_latent_isolation.py` proves latent
fields are absent from the model-input tables and from `data/canonical`.
**Note:** `marginal_roas` legitimately appears on the `recommendation` *output*
table (an optimizer result), so the leakage check is scoped to input tables.

## D-010 — Two-level record validation + quarantine utility
> **Status: SUPERSEDED BY D-020 — removed from active Stage 0 scope; reconsider during Stage 2.**
> `schemas/validation.py` and `tests/test_record_validation.py` were deleted in the
> scope reset. Stage 0 represents quarantine *states* via `data_quality_issue` and
> `sku_alias.match_status`; it ships no reusable record-validation/quarantine
> service. The design below is retained as the Stage-2 spec.

**Stage 0 (Codex blocking fix 2).** Whole-envelope rejection was the only thing
tested. **Decision:** add a small reusable utility
(`schemas/validation.py`) that validates the outer envelope structure, then each
record independently, keeps valid records flowing, and quarantines invalid ones
with full provenance (platform, source index/key, errors, raw payload, timestamp,
status). Quarantine is a **separate artifact**, not mixed into the 11 planted
defects (their counts stay independent). This is a utility, **not** the full
Stage-2 ingestion service. `test_record_validation.py` covers mixed
valid/invalid envelopes.

## D-011 — Reproducible dependency lock
**Stage 0 (Codex important fix 1).** Docs claimed "pinned" while `pyproject.toml`
used ranges. **Decision:** commit `requirements-lock.txt` (exact tested versions +
Python version in the header); `make setup` installs from the lock and the package
with `--no-deps`; `make setup-dev` keeps the range install for development.
`make verify-clean-install` builds a throwaway venv from the lock and runs the
suite. Bumps are recorded here.

## D-012 — Independent defect contract fixture
**Stage 0 (Codex important fix 2).** Tests imported expected counts from the
production constant. **Decision:** add `tests/fixtures/expected_defects.json` as
an independent contract; tests read it, and a separate test asserts the
production constant agrees with the fixture — so changing the backend without
updating the contract fails. Realized-data tests (deriving each defect from the
generated records) are retained.

## D-013 — Generated manifest with logical fingerprints
**Stage 0 (Codex important fix 3).** **Decision:** add `synth/manifest.py` writing
`data/canonical/manifest.json` with seed, generator/schema version, Python +
dependency versions, row counts, per-table and per-envelope **logical**
fingerprints (canonical JSON, stable ordering — never Parquet bytes),
reference-artifact fingerprints, an optional latent fingerprint (opt-in only), and
a combined fingerprint. `test_fingerprints.py` proves canonical-table drift and
raw-envelope drift change the appropriate fingerprints.

## D-014 — Google `new_customers` field renamed
**Stage 0 (Codex optional fix).** The Google envelope field held a new-customer
**count** but was named `new_customer_lifetime_value`. **Decision:** rename to
`new_customers` (matches Google's `metrics.new_customers`) in
`schemas/envelopes.py` and the writer.

## D-015 — Validation continues THROUGH normalization into canonical rows
> **Status: SUPERSEDED BY D-020 — removed from active Stage 0 scope; reconsider during Stage 2.**
> `backend/decision_engine/ingestion.py` was deleted in the scope reset. Raw-record →
> canonical normalization is Stage-2 ingestion work; Stage 0 does not normalize
> raw platform records. The design below is retained as the Stage-2 spec.

**Stage 0 (2nd review).** Record-level validation preserved valid records but did
not prove they continue into canonical normalization. **Decision:** add
`backend/decision_engine/ingestion.py` — small Meta/Google normalizers (validated
record → canonical ad-performance row, with `cost_micros` → currency and
segment/SKU enriched from the campaign dim) plus `validate_and_normalize_*`. Valid
records become canonical rows; invalid records are quarantined and never enter
canonical output. Still a utility, **not** the Stage-2 service.

## D-016 — Full-artifact fingerprint is the main reproducibility hash
**Stage 0 (2nd review).** The combined hash covered canonical tables only.
**Decision:** name two fingerprints explicitly — `canonical_tables_fingerprint`
(tables only) and `full_artifact_fingerprint` (the MAIN one: every canonical
table + Meta/Google/Shopify envelopes + generator/schema versions + seed +
dependency versions). Manifest, CLI, README, and the regression test use the full
fingerprint. Logical content is hashed with canonical JSON (never Parquet bytes),
so formatting cannot change it. Drift tests cover canonical, envelope, and
dependency-version changes.

## D-017 — Typed empty operational tables (no object/null inference)
**Stage 0 (2nd review).** **Decision:** derive an explicit Arrow schema and DuckDB
DDL from each table's Pandera contract (`arrow_schema` / `duckdb_columns`). Empty
operational tables (`model_run` … `execution_event`) are written to Parquet with
the Arrow schema and created in DuckDB via explicit DDL, so their declared types
survive even with zero rows. `test_typed_tables.py` inspects both.

## D-018 — `make lint` is enforcing
**Stage 0 (2nd review).** Removed `|| true` from `make lint` (now exits non-zero
on any Ruff violation). Added `make lint-report` (`ruff --exit-zero`) for a
non-failing report.

## D-019 — Small cleanups
**Stage 0 (2nd review).** Removed a duplicate `CONSERVATIVE_Z` definition in
`config.py`. Corrected the `pyproject.toml` comment: reproducible installation is
pinned via `requirements-lock.txt`; package metadata intentionally uses
compatible ranges. Latent-truth isolation (D-009) unchanged.

## D-020 — Scope reset to the Stage 0 boundary (supersedes parts of D-007/8/10/15)
**Stage 0 (scope correction).** Successive reviews pushed legitimate-but-premature
Stage 2/3 machinery into Stage 0. The original mandate is "implement Stage 0 only;
do not build the system in one pass." **Decision:** remove the out-of-scope code
and defer it (with its design rationale) to its proper stage. The deferred design
notes below are the spec for those stages — the work is not lost, just relocated.

**Removed from the Stage 0 tree:**
- `backend/decision_engine/ingestion.py` — raw-record → canonical **normalization**.
  **Deferred to Stage 2** (real ingestion adapters). Design captured: Meta/Google
  record normalizers fill all canonical fields with documented defaults
  (`label_mature` set by the maturity stage, `is_duplicate` by the dedup stage,
  Meta `new_customers=None`); records with no usable date are quarantined, not
  imputed; the result validates against the `fact_ad_performance` Pandera schema.
- `backend/decision_engine/schemas/validation.py` — reusable envelope/record
  **validation + quarantine utility**. **Deferred to Stage 2.** Stage 0 only needs
  quarantine *states* representable, which `data_quality_issue` and
  `sku_alias.match_status` already provide.
- `tests/_feasibility.py` — constrained **allocation search**. **Deferred to
  Stage 3** (SLSQP optimizer). Design captured: the search honored ±20% movement,
  caps, inventory no-scale, prospecting floor, budget/reserve, ROAS floor, and
  contribution lift; the scenario has a non-empty feasible region (a valid
  candidate ≈4.10 ROAS exists). Stage 0 must NOT advertise an optimizer allocation.
- `tests/test_record_validation.py` — Stage-2 mixed-record ingestion tests.
- `economics.py` **efficiency hurdle / reserve-feasibility** and per-campaign
  hurdle helpers; `config.EFFICIENCY_SAFETY`. **Deferred to Stage 3/4** (reserve
  modes). Design captured: efficiency-first uses a stricter hurdle
  (break-even × ~1.6) under which holding budget in reserve becomes feasible.

**Retained (all genuinely Stage 0):** dependency lock (D-011), independent defect
contract fixture (D-012), full-artifact manifest + logical fingerprints
(D-013/D-016), typed empty operational tables (D-017), latent-truth isolation
(D-009), enforcing `make lint` (D-018), the economically-derived **scale floor**
(break-even × `HARD_FLOOR_SAFETY`, used only to characterize the scenario's latent
truth), and the de-knife-edged scenario.

**Test impact:** allocation-search and ingestion tests replaced by broad
scenario-contract properties in `test_business_invariants.py`
(`test_scenario_supports_a_future_feasible_optimization`): saturated channels and
headroom channels coexist, prospecting is fundable, exactly one SKU is inventory
constrained, and current calibrated blended ROAS is below target — **without**
computing any allocation.

**Revisions:** D-007's efficiency-hurdle/reserve content and D-008's "feasibility
witness" content are deferred per this entry; their *scenario-design* facts
(margin-derived scale floor; calibrated-below-target with an over-attribution gap)
remain valid and tested.

## D-021 — Stage 1 thin end-to-end shell (FastAPI + Next.js)
**Stage 1.** Build the working **browser → API → decision → approve/audit** seam
before any modeling (FINAL_PLAN §11). **Decisions:**
- **Single backend service: FastAPI** (`backend/api/`). No separate Express
  service — Next.js already covers the Node/TS side; a second backend purely to
  name a framework is negative value (FINAL_PLAN §10).
- **One FIXED placeholder recommendation** (`backend/api/recommendation.py`),
  built deterministically from the canonical dataset (dim_campaign + current
  spend) plus a STATIC per-campaign delta fixture that mirrors the golden
  scenario's directions. It is **explicitly labelled `is_fixed_placeholder`** and
  is NOT an optimizer result — Stage 3 replaces it with SLSQP. KPIs that are
  observable from canonical data are computed; the projected ROAS is a labelled
  fixture.
- **Stubbed, in-memory audit** (`backend/api/store.py`): approve/reject is
  recorded; approval is **idempotent**; a **rejected** recommendation never emits
  execution events; a conflicting decision returns **409**. On approval, one
  stubbed execution payload per platform is generated (no OAuth, no live writes),
  and the **inventory-blocked** campaign's change is excluded. A durable audit
  store arrives in Stage 4.
- **Minimal Next.js page** (`frontend/`, app router + TS, hand-rolled — no
  `create-next-app`/shadcn churn yet): KPI cards, the current→recommended table
  with reason/risk chips, and Approve/Reject. shadcn/Recharts polish is deferred
  to Stage 4.
- **API stack added to the lock**: `fastapi`, `uvicorn[standard]`, `httpx`
  (TestClient) are now in `requirements-lock.txt` and the `api`/`dev` extras, so
  `make setup` yields a runnable backend. The full-artifact fingerprint is
  **unchanged** (it hashes only the 6 core data deps, not the API stack).
- **Tests** (`tests/test_api.py`, 8): recommendation shape/directions, stubbed
  execution on approve, no-execution on reject, idempotent approval, 409 conflict,
  404 unknown rec. The 96 engine tests stay green (104 total).
**New `make` targets:** `api`, `web-setup`, `web`.

**Stage 1 review remediation (Codex):**
- **Lifecycle status in the contract.** `GET /api/recommendation` now returns
  `status` (`pending`/`approved`/`rejected`) reflected from the audit store, and
  the frontend hydrates from it on load (a refreshed page shows a prior decision
  and disables the actions). The decision record gained `action`,
  `previous_status`, `new_status`. A **durable, append-only, multi-entry audit
  history remains Stage 4** — deliberately not built here (avoiding the earlier
  over-reach); the Stage 1 record is a single decision with its transition.
- **Env docs.** `.env.example` corrected to `API_HOST`/`API_PORT` and
  `NEXT_PUBLIC_API_BASE` (and de-branded from the stale stale legacy env vars).
- **Frontend quality gate.** Added ESLint (`eslint` + `eslint-config-next` +
  `.eslintrc.json`); `npm run lint` now runs non-interactively and passes.
- **Reproducibility.** `package-lock.json` is committed; `make web-setup` uses
  `npm ci`.
- **Next.js security.** Bumped `next` 14.2.15 → **14.2.35** (removes the critical
  CVE). Residual advisories are inherent to the 14.x line and mostly inapplicable
  to this **statically-prerendered** single page (no Image Optimizer, middleware,
  or rewrites); a Next 15 upgrade is a **Stage 6 hardening** item.
- **Deferred (Stage 6):** a browser-level E2E of the approval flow. The
  approve/reject/idempotent/409 logic is covered by `tests/test_api.py`; build +
  `tsc --noEmit` + ESLint are the frontend gates for now.

## D-022 — Stage 2 real ingestion (adapters, validation/quarantine, SKU resolution, DQ)
**Stage 2.** Replace the in-memory fixture path with real ingestion of the raw
API-shaped JSON (FINAL_PLAN §11). New package `backend/decision_engine/ingestion/`:
- **adapters** flatten Meta `data/paging` (numeric strings, `actions`), Google
  nested `results` (`cost_micros` → currency), and Shopify into the canonical
  model, enriching segment/SKU from the campaign reference; every surviving record
  is a **schema-valid** `fact_ad_performance` / `fact_commerce_truth` row.
- **two-level validation** (`validation.py`): structurally-valid envelope, then
  each record independently; bad records **quarantined** with provenance, never
  discarding the export. Google rows with no `segments.date` can't be placed and
  are quarantined (flag, don't impute).
- **SKU reconciliation** (`sku_resolution.py`): deterministic
  auto/needs-approval/quarantine states from `sku_alias`, with an
  `allowed_candidates` list (the bounded set a Stage-5 LLM would later *rank* — the
  schema forbids inventing a SKU outside it). A human approves the needs-approval
  candidate via the API/UI.
- **data-quality detection** (`quality.py`) from the feeds: dedup on natural key,
  missing-date quarantine, `cost_micros` normalization, null new-customer
  (Shopify), platform>Shopify reconciliation, coverage gaps, and label maturity
  (`extraction_date − date ≥ 7d`).
- **API**: `GET /api/ingestion` (feed counts, canonical row counts, quarantine,
  detected DQ issues, SKU resolution) and
  `POST /api/sku-resolution/{id}/approve`. **Frontend**: an *Ingestion &
  reconciliation* page (feed stats, SKU table with Approve, DQ table).

**Scope/honesty notes:**
- The Google `extraction_date` is not in the raw feed; the adapter backfills it as
  the feed's latest metric date (the pull date proxy) so label maturity is sane.
- A few Stage 0 *canonical-level* defects are **not carried by the raw envelopes**
  and so are out of feed-level detection scope (the Google attribution-window
  mismatch; the Meta new-customer nulls — Meta insights don't expose new-customer
  count). Detected DQ therefore reflects what the feeds actually observe, not a
  1:1 replay of the 21 planted canonical issues. This restores the
  validation/normalization work deferred in **D-020**, now in its proper stage.
- **Tests:** `tests/test_ingestion.py` + ingestion API tests; 122 total.
  The data fingerprint is unchanged (ingestion reads the same raw feeds).

**Stage 2 review remediation (Codex):**
- **Deterministic ingestion report (blocking).** Quarantine records stamped
  `detected_at` with `datetime.now()`, so two runs differed. Fixed: a deterministic
  `as_of` (the feed pull date, the latest metric date across feeds) is threaded
  through validation/adapters and used for `detected_at`; no wall-clock anywhere in
  ingestion. `test_ingestion_report_is_deterministic` guards it. (The Stage 1 audit
  `decided_at` stays wall-clock — that's a genuine human runtime action, not a
  deterministic data transform.)
- **Quarantine source-index provenance.** The missing-date Google quarantines used
  `source_index=-1`; now the original feed position is preserved via
  `ValidationResult.valid_indices`.
- **Evidence-gated cost-micros.** `google_cost_micros_normalization` is only emitted
  when Google rows were actually ingested.
- **Platform-scoped natural key.** Dedup key is now `(platform, campaign_id, date)`
  — vendor IDs aren't globally unique.
- **Stronger maturity test:** asserts immature == exactly the final 7 calendar days,
  nothing in the tail is mature, and the policy applies across every platform.

## D-023 — Stage 3 real engine (forecast + residualized response + SLSQP optimizer)
**Stage 3.** Replace the Stage 1 fixed placeholder with a deterministic engine that
**recovers the golden scenario from the OBSERVABLE canonical data** (FINAL_PLAN §5–6).
`backend/decision_engine/engine/`:
- **Model B — response (`response.py`).** Identifying media response is confounded:
  in this data spend co-moves with day-of-week/promo/trend, so naively residualizing
  revenue against those controls also strips the media effect (first attempt gave
  near-zero marginals). **Decision:** use **orthogonalization (Frisch–Waugh–Lovell /
  double-ML)** — out-of-fold control models residualize BOTH calibrated revenue and
  spend, then a local quadratic of revenue-residual on spend-residual gives the
  marginal ROAS. This recovers the marginal **ordering** almost exactly
  (`NONBRAND > PMAX > SHOPPING > ADV > PROSPECTING > RETARGETING ≈ BRAND`), matching
  truth; magnitudes are compressed but directions are right — which is what drives
  the allocation. Block-bootstrap gives a downside (Conservative) marginal. Used only
  within the ±20% movement support; not a causal-identification claim.
- **Model A — BAU forecast (`bau_forecast.py`, `baselines.py`).** XGBoost **quantile**
  P10/P50/P90 of 7-day calibrated revenue, **monotonic in spend**, trained on
  label-mature rows, **gap-aware walk-forward** validation (7-day gap), **promoted
  only if it beats** the trailing-14d / same-weekday baselines (else the baseline is
  the fallback — both happen across the 7 campaigns). Deterministic (fixed seed,
  `n_jobs=1`).
- **Optimizer (`optimizer.py`).** SciPy **SLSQP** maximizing calibrated net
  contribution `Σ[R_i(b_i)·m_i − b_i]` subject to: reported blended ROAS ≥ 4.0,
  prospecting share ≥ floor, NC-CPA ≤ target, ±20% movement, inventory no-scale,
  budget (+ optional reserve). A pre-solve feasibility check yields an explicit
  **conflict report** for contradictory constraints, never an invalid plan.

**Design decisions:**
- ~~**The enforced ROAS floor is the PLATFORM-REPORTED blended ROAS**~~ **— SUPERSEDED
  by the remediation below.** *(Original rationale, kept for history: the compressed
  marginals couldn't lift calibrated ROAS across 4.0, so the reported metric was
  enforced instead.* After the adstocked-double-ML fidelity fix, the calibrated
  blended ROAS reaches 4.06 and is the **enforced** floor again, per D-008; reported
  ROAS (~6.25×) is shown as context — the "dashboard says 6.2× but the incremental
  reality is ~4.0×" story.*)*
- **`PROSPECTING_MIN_SHARE` 0.35 → 0.33.** The prospecting campaigns cap out early, so
  their daily caps physically limit prospecting to ~0.335 of the (trend-inflated)
  budget; a 0.35 floor was infeasible. 0.33 still binds (current ~0.315) without
  contradicting the caps.
- **Dependencies:** `scipy`, `scikit-learn`, `xgboost` added to the lock. **xgboost
  needs the OpenMP system runtime** (`brew install libomp` on macOS) — documented in
  the lock header, pyproject, and README.

**Wiring:** the API recommendation (`REC-OPT-0001`, `engine=slsqp_optimizer`,
`is_fixed_placeholder=False`) and the frontend now show optimizer output — marginal
ROAS, reported vs calibrated ROAS, feasibility/conflicts, and the 7-day P50 forecast.
**Tests:** `tests/test_engine.py` (13) assert recovered directions, constraint
satisfaction, marginal ordering, Conservative downside, quantile ordering,
determinism, and an infeasibility conflict report; 137 total. Data fingerprint
unchanged (the engine reads, never regenerates).

**Deferred:** the calibration-sensitivity view is Stage 4 trust-controls work.
(The forecasting/saturation **charts** were brought forward — Recharts: reallocation,
marginal-ROAS-vs-floor, saturation curves, P10/P50/P90 forecast.)

**Stage 3 review remediation (Codex) — supersedes parts of the above:**
- **Magnitude fidelity (keystone).** The local quadratic on *raw* spend compressed
  magnitudes (only ~43% of channels classified correctly vs the floor) because raw
  spend is a noisy proxy for the adstocked spend revenue responds to
  (errors-in-variables). **Fixed:** residualize on **adstocked** spend with a
  per-campaign decay grid. Recovered marginals are now close to truth
  (e.g. nonbrand 6.1 vs 5.5; pmax 2.96 vs 3.15) and **classification vs the floor is
  ~100% correct** — only Brand/Retargeting fall below.
- **Calibrated ROAS floor restored.** With correct magnitudes the optimizer can lift
  **calibrated** blended ROAS 3.76 → **4.06** (≥4.0), so the enforced floor is the
  calibrated (incremental) ROAS again — **per D-008**, not the reported basis. Reported
  ROAS (6.25) is shown as context. *This supersedes the earlier reported-floor decision.*
- **Marginal-floor + learning-budget + solver constraints.** Below-floor campaigns
  cannot increase (bound to current); the ±20% lower bound also enforces the minimum
  learning budget; `_check_feasibility` now also requires SLSQP convergence.
- **Infeasible plans cannot be approved.** `POST …/decision` returns **422** on
  approve when `feasible=False` (reject is still allowed). Test added.
- **Expected vs Conservative now differ.** The downside estimate is barely lower
  (robust scenario), so Conservative also takes **smaller steps (±15%)**; it honestly
  reports the 4.0 floor as just out of reach under cautious movement (≈3.99) —
  the plan's closest-feasible-with-shortfall behavior. Expected stays the feasible view.
- **BAU target off-by-6 bug fixed** — `target_fwd7[i]` now sums days `i…i+6` (was
  `i+6…i+12`). **Reason codes reconciled** — an increase below the floor is labelled
  `constraint_driven_increase`, never `room_to_scale`.
- **Known limitation (documented, not blocking):** NC-CPA uses an observable
  new-customers-per-$ ratio (Meta exposes no new-customer count); it is currently
  non-binding (large slack). A spend-responsive new-customer model is a refinement.
- **Tests:** 140 total; new engine/API tests for the calibrated floor, no-below-floor
  increase, Conservative-vs-Expected, and the infeasible-approval block.

## D-024 — Interactive constraint adjustment (brief M3 "adjust constraints")
**Stage 3.** The brief's M3 requires the marketer to "review recommendations,
**adjust constraints**, and approve or reject before execution." Implemented:
- The optimizer constraints (ROAS floor, NC-CPA target, prospecting-min share,
  movement bound) and the risk policy (Expected/Conservative) are now **adjustable
  at request time** — `optimize()` takes them as parameters (defaults = config).
- **Performance:** the expensive engine state (residualized responses + XGBoost
  forecast + masters) is **constraint-independent**, so it is cached once
  (`_context`, ~2 s cold) and only the SLSQP solve re-runs (~**10 ms**). The
  marketer can drag a slider and see the plan re-solve live.
- **API:** validated `GET /api/recommendation?policy=&roas_floor=&nc_cpa_target=&
  prospecting_min_share=&movement_bound=` (out-of-range / NaN / inf / wrong-policy →
  **422**). The plan's constraints are echoed in `constraints`.
- **UI:** a constraints panel (policy toggle + four numeric controls + Reset);
  tightening past feasibility shows the conflict report and disables Approve.
  Loosening (e.g. movement 0.20→0.30) visibly lifts calibrated ROAS (4.06→4.23).
  Conservative uses the downside response and 75% of the chosen movement bound —
  never more aggressive than Expected.

**Review remediation (Codex/GPT) — immutable scenario snapshots, supersedes the
original "approval re-solves" design:**
- **Each plan has a deterministic `scenario_id`** = hash(policy + constraints +
  `data_fingerprint` + `engine_version`). `GET` stores the plan as an **immutable
  snapshot**; the response carries `scenario_id`, `data_fingerprint`, `engine_version`.
- **Approval binds to a stored snapshot by id and never re-solves** (`POST
  /api/recommendation/{scenario_id}/decision`). This fixes the bug where every
  constraint set shared `REC-OPT-0001` and approving one marked others approved.
  An unknown/stale id → **404**; an infeasible snapshot → **422** on approve. The
  audit records the snapshot's exact policy, constraints, and allocation.
- **Constraint validation** (Pydantic + `Query` bounds) rejects unsafe values —
  e.g. `movement_bound=10` (which previously produced approvable **negative spend**),
  NaN/inf, negatives, and non-`Literal` policy.
- **Frontend dirty-guard:** Approve/Reject are disabled while solving or when the
  inputs no longer match the displayed plan — you can only decide the exact plan shown.
- **Honest infeasible label:** the infeasible allocation is a **diagnostic candidate**
  (the clipped solver iterate), explicitly NOT a proven closest-feasible plan.
- **Conflict reporting** now states **exact shortfalls** (e.g. "calibrated blended
  ROAS 4.064× < floor 5.00× (short 0.936×)") and leads with the binding constraint
  rather than a bare "SLSQP did not converge"; bounds-enforced constraints (caps,
  inventory, movement, marginal floor) can't be violated so don't appear.
- **Tests:** scenario-identity isolation, validation 422s, stale-scenario 404,
  exact-shortfall conflicts, blocked infeasible approval. 144 total.

**Review remediation round 2 (Codex re-review) — version-locked snapshots +
provenance:**
- **`scenario_id` now also folds in a `config_fingerprint`** (hash of the
  policy/economics constants + the Conservative 0.75 movement factor), so a config
  change can no longer collide with an existing id and silently map to a different
  allocation.
- **`GET` returns the CANONICAL stored snapshot** (not a freshly built object), so
  the displayed plan is byte-for-byte what approval binds to — no `generated_at`
  drift between view and approve.
- **Stale = engine state changed, made real.** Approval compares the snapshot's
  `(data_fingerprint, engine_version, config_fingerprint)` to the *current* engine
  provenance; a mismatch → **409 stale, recalculate**. Approving an earlier *known*
  scenario under unchanged state stays allowed (the deliberate **snapshot-library**
  semantic GPT specified) and binds to that snapshot's exact allocation — now a
  tested contract.
- **Audit provenance complete:** the decision record carries `data_fingerprint`,
  `engine_version`, and `config_fingerprint`, so an approved plan ties back to the
  full modeling/config state.
- **NC-CPA conflict precision:** the target is no longer rounded (`:.0f`→`:.2f`),
  killing false claims like "$5.73 > target $6".
- **Bounded snapshot store** (LRU, cap 512): memory is bounded and very old
  snapshots expire (an evicted id reads as stale → 404).
- **Transparency / UX:** the API returns the `effective_movement_bound` (Conservative
  0.20→0.15, shown in the UI); share/movement controls display **percentages** not
  raw fractions; the UI seeds defaults from the backend (no hard-coded drift) and
  surfaces the backend's 422 validation detail instead of hanging on "Recomputing";
  the infeasible banner is relabelled "Unmet constraints (exact shortfalls)".
- **Position held (not a bug):** a stateless API has no well-defined "latest"
  scenario, so older *known* snapshots remain approvable under unchanged state; the
  version check + UI dirty-guard are the real safety, not a "reject older" rule.
- **Tests:** NC-CPA fractional precision, full audit provenance, returned≡stored
  (no drift), stale-on-engine-change 409, known-older-scenario approval contract,
  effective-movement exposure. 157 total.

**Review remediation round 3 (Codex re-review) — accurate provenance + supersession:**
- **Data fingerprint is now the ACTUAL modeling panel** (`frame_fingerprint(panel)`),
  not a parallel `generate()` of master tables — so the identity reflects the real
  post-ingestion/dedup/feature inputs the engine trains on.
- **Config fingerprint is now LIVE** (`config_fingerprint()` reads `config.py` on
  every call, no longer frozen at import) and folds in the engine-side Conservative
  0.75 factor. A genuine config change moves the fingerprint, the `scenario_id`, and
  trips the approval **stale check (409)** — verified by a test that patches a real
  config value (not the provenance function). Engine bumped to `stage3.3`.
- **Supersession guard (chosen via product decision):** the snapshot store tracks
  the most-recently-computed (**active**) scenario; approving a **superseded** plan
  returns **409 "recalculate"** (rejecting it stays allowed — it never executes).
  Re-computing an older scenario makes it active again. This adopts the reviewer's
  acceptance criterion over the pure snapshot-library model; snapshots remain
  immutable and the audit/idempotency contracts are unchanged. **Known limitation:**
  the active pointer is global (single-marketer demo); concurrent tabs/users would
  contend — acceptable here, a per-session pointer is a Stage-4 concern.
- **Scope boundary stated honestly:** the engine context is process-cached under the
  pinned-data, **restart-to-change** contract; a real data change means a cold
  rebuild → new panel fingerprint. Runtime hot-swap cache invalidation is a Stage-4
  durable-runtime concern, not faked here.
- **Tests:** real-config-change stale 409, config-change → new scenario_id,
  superseded-rejected-but-rejectable, recompute-makes-active-again. 160 total.

## D-025 — Stage 3 structured binding report + Model A→optimizer level wiring
**Stage 3 (pre-Stage-4 remediation, two AI reviewers agreeing).** Two findings from
a model/data review (Cursor + GPT) were closed before broad Stage 4 work.

**(a) Structured binding-constraints report (reporting completeness).** The optimizer
now emits a *positive* "why this plan" view (`optimizer._binding_report`): each
portfolio business constraint with a `binding | slack | violated` status and exact
margin (budget-fully-deployed, calibrated-ROAS-floor, prospecting-min-share,
NC-CPA), plus the hard bound that pins each moved campaign (`movement_up_cap` /
`movement_down_floor` / `daily_cap` / `inventory_no_scale` / `below_hurdle_no_increase`).
This complements the unmet-`conflicts` list (hard bounds can't be violated, so they
never appeared there). Surfaced via `Recommendation.binding` and a "Why this plan" UI
panel. At the default optimum the **ROAS floor is slack (+0.06×)** and the
**prospecting-min-share is the binding constraint** — the real margin of safety.

**(b) Model A (BAU forecast) now feeds the optimizer — the M2→M3 level anchor
(architecture wiring gap).** FINAL_PLAN §5 specifies `Ŷ(b) = Ŷ_BAU(b_current) +
[R(b) − R(b_current)]`: BAU owns the level, the response owns the spend-change delta.
The response curve already had this anchored-delta shape, but its **level** came from a
trailing-14-day daily mean — so the elaborate XGBoost forecast (and its validation
report) **never fed the allocation**. **Decision:** anchor the per-campaign revenue
level on the **selected** BAU model's forward-horizon P50, converted to an **average
daily level** (`÷ FORECAST_HORIZON_DAYS`, a new single-source config constant) to match
the daily-budget optimizer — **not** the raw 7-day total (which would inflate revenue
~7× and ROAS to ~26×). Only the level moves; the response slope/quad/downside (the
delta) and the marginal at current spend are unchanged, and the delta stays exactly
zero at current spend.
- **Measured shift before wiring:** for the 5 fallback campaigns `BAU_p50/H` equals the
  trailing-14d daily mean **by construction** (0.0% shift); only the 2 XGBoost-promoted
  campaigns move (GOOGLE_BRAND +0.5%, META_PROSPECTING +1.2%). Portfolio calibrated
  revenue +0.2%.
- **Outcome (no retuning):** calibrated blended ROAS **3.77 → 4.07** (was 3.76 → 4.06);
  the plan stays feasible and the floor still clears honestly. The forecast report is now
  decision-relevant. Engine bumped to **`stage3.4`**; `level_anchor =
  "selected_bau_p50_over_horizon"` is persisted in the recommendation for audit.
- **Tests (engine):** no-7×-scale band, delta-zero-at-current-spend, level == selected
  BAU ÷ horizon, fallback-uses-baseline / xgb-uses-xgb. 165 total. Data fingerprint
  unchanged. Model report regenerated under stage3.4.

**Known limitations (documented honestly, scheduled for Stage 4, NOT papered over):**
- **NC-CPA is an approximate *monitored guardrail*, not a meaningful binding optimizer
  constraint.** Projected NC-CPA (~$6) sits far under the $45 ceiling, so it never binds;
  prospecting-min-share is what actually protects top-of-funnel. The new-customer signal
  is a fixed observable ratio (Meta exposes no new-customer count), not a spend-responsive
  model. A real BAU+delta **new-customer response** (Model A's second target per §5) is a
  Stage-4 modeling build.
- **80% prediction interval is uncalibrated (too narrow: coverage ~0.43 vs 0.80).** The
  decision basis is the marginal ordering + the ROAS floor, **not** the P10/P90 band; do
  not use the band for risk sizing yet. Conformal/residual calibration **around the
  selected point model** (not auto-XGBoost) is Stage-4 trust-controls work. Conservative
  therefore uses the same level anchor + the downside response (not the uncalibrated P10).
- **Calibration error is not yet tested:** the calibration registry copies the scenario's
  true incrementality, so "calibrated revenue" carries no calibration uncertainty. A
  Stage-4 **calibration-coefficient sensitivity** view (perturbed/uncertainty-range
  coefficients) and a separate **stress scenario** are the right places to exercise it —
  the golden scenario stays the clean deterministic contract.
- **~~Forecast model-selection differs between the live `forecast()` and the eval
  harness~~ — RESOLVED in D-026.** Both selectors were reconciled onto one shared
  frozen policy (`engine/selection.py`), so the UI and the report always report the
  same selected model.

## D-026 — Feed-observable attribution conflict + unified BAU model selector
**Stage 3 (pre-Stage-4 remediation, three AI reviewers agreeing: Cursor + Codex +
GPT).** Two demo-visible contradictions identified in the M1/M2 review were closed
before freezing Stages 0–3.

**(a) Google attribution-window conflict is now detected at the FEED boundary (M1).**
The brief asks to surface attribution conflicts. Previously the planted GOOGLE_BRAND
`last_click` mismatch lived only in canonical truth: the Google adapter **hardcoded**
the canonical window (`data_driven`), silently normalizing the conflict away at ingest,
so it was never detected from the feed. **Decision:** make attribution **feed-observable**
and compare, never reconcile —
- the raw Google envelope now carries `campaign.attribution_model` (new required field
  on `GoogleCampaign`); the writer emits the observed per-campaign value (GOOGLE_BRAND =
  `last_click`, everyone else `data_driven`);
- the adapter **preserves** the observed value (`rec.campaign.attribution_model`) instead
  of overwriting it with the policy;
- `ingestion/quality.py` compares each campaign's **observed** model against the
  **canonical comparison policy** (`CANONICAL_ATTRIBUTION_POLICY`) and emits an
  `attribution_window_mismatch` DQ row ("GOOGLE_BRAND reports 'last_click'; policy expects
  'data_driven' — platform ROAS retained but not directly comparable until calibrated"),
  surfaced in the Ingestion UI alongside the other DQ issues. **No revenue is reconciled.**
- **Fingerprint:** because the raw Google envelope shape changed, the **full-artifact
  fingerprint** was deliberately bumped (`16d51091… → aa27fe98…`); the
  **canonical-tables** fingerprint is **unchanged** (generator truth untouched). Recorded
  here per the D-009 contract.
- **Tests:** feed carries observed model (GOOGLE_BRAND = `last_click`); conflict detected
  with observed-vs-expected text; adapter did not normalize the value away.

**(b) ONE shared, frozen BAU model selector (M2) — the UI and the report can no longer
disagree.** Previously the live engine selected on a full-series MAE walk-forward while
the eval harness selected on a fixed-window validation WAPE, so the per-campaign "selected
model" could differ between the UI and the report. **Decision:** extract a single
`engine/selection.py::select_models(panel)` used by **both** `bau_forecast.forecast`
(the optimizer's anchor) and `eval/harness.evaluate_forecast` (the report). It selects on
**pre-test chronological folds only** (gap-aware; the last fold's 7-day target ends at t=167
< the test start 168), so the untouched test period is never consulted — the report still
*scores* the frozen choice on test, it just can't change it.
- **Policy (baseline-default, GPT's stricter bar):** the trailing-14d baseline wins unless
  XGBoost beats the best baseline's pooled WAPE by ≥ `MATERIAL_WAPE_IMPROVEMENT` (5%) AND
  wins a majority of folds AND is not materially more biased. Each decision returns
  auditable metadata (per-fold wins, pooled WAPE/bias, improvement %, threshold, reason),
  persisted in `bau_forecast` for audit and exposed in the report's `selection` block.
- **Outcome:** under the unified policy **2 campaigns promote to XGBoost** (GOOGLE_BRAND
  +23.7% WAPE, GOOGLE_NONBRAND +5.0%) and **5 fall back** to the baseline — and the engine
  and report now agree campaign-for-campaign (verified). META_PROSPECTING, which the old
  engine selector had promoted, correctly falls back (it improved by only −23% i.e. worse),
  so its anchor reverts to the baseline daily mean. **Calibrated blended ROAS 3.76 → 4.06**
  (vs 3.77 → 4.07 at stage3.4); plan stays feasible, floor still clears honestly.
- **Engine bumped to `stage3.5`**; model report regenerated (WAPE 0.033, safe_for_demo
  true). The pure promotion policy is unit-tested without training XGBoost (heavy XGBoost
  runs stay in `make model-report`, per the fast-deterministic-suite norm). The promotion
  threshold is **inclusive and gated on the raw WAPE fraction** (not the rounded display %),
  so a 4.96% improvement cannot be promoted — boundary-tested. (GOOGLE_NONBRAND sits right at
  the bar: raw improvement 5.008%, 3/3 folds, bias guard passed.)
- **Honest generalization caveat (frozen, NOT flipped — no test leakage):** on the *untouched
  test* period the two pre-test-promoted campaigns actually **lose** to their baselines
  (GOOGLE_BRAND xgb 0.018 vs trail-14d 0.015; GOOGLE_NONBRAND xgb 0.057 vs 0.041), while a
  *fallback* campaign (META_ADV_SHOPPING) would have materially beaten its baseline on test.
  This is the expected selection-vs-realization gap from choosing on pre-test folds only; we
  **do not** re-pick using test results (that would leak test into the policy). The report
  now states this explicitly (§3). The anchor effect is small and the decision basis is the
  marginal-ROAS ordering + the ROAS floor — not the absolute BAU level — so this does not
  change the recommendation's safety. A more representative fold layout (earlier/longer
  pre-test windows) is a principled, leakage-free Stage-4 selector refinement.

**(c) Honest M2 wording.** The response visual is relabelled from "Saturation / response
curves" to **"Local spend-response estimate"** (estimated marginal ROAS within observed
support; not a fitted saturation model). The README states the **platform scope** plainly:
the runnable slice is **Meta + Google**; **Amazon is not implemented** and follows the same
connector + canonical-schema pattern as the next extension (no new decision logic).

## D-027 — Stage 4.1: reserve / efficiency-first modes + pacing utilization
**Stage 4 (trust & business controls).** First Stage-4 slice. Adds the **waste-control
lever** the brief asks for (success criterion #3: "inefficient campaigns burning full
budgets… efficient campaigns hitting caps leaving revenue on the table") as a first-class,
deterministic optimizer mode plus a pacing view — no new magic numbers, no LLM.

**(a) Budget mode (`reserve_mode`: `growth` | `efficiency_first`).** Threaded through the
whole slice: `ConstraintParams` / `Constraints` → `build_engine_recommendation` →
`optimizer.optimize(reserve_allowed=…)` → API query param → UI toggle. `growth` keeps the
existing budget **equality** (deploy 100%); `efficiency_first` uses the budget **inequality**
(`spend ≤ B`) that already existed in `optimizer.py`, so the solver may **hold budget in
reserve** when the next dollar can't clear its own contribution hurdle. Because the inequality
region is a **superset** of the equality region, efficiency-first can never earn less
contribution and never holds negative reserve — both asserted as invariants
(`tests/test_pacing.py`), not exact dollars.
- **Mode folds into `scenario_id`** (it is part of `ConstraintParams`), so growth vs
  efficiency-first are distinct, separately-approvable snapshots — supersession/stale guards
  apply unchanged.
- **Demo beat:** in the clean golden scenario both modes deploy fully (reserve $0 — an honest
  "healthy portfolio fully deploys"). Tighten `roas_floor` to 4.1 and **growth goes
  infeasible** (can't hold the floor at 100% deployment) while **efficiency-first stays
  feasible, holding ≈ $714 in reserve** and meeting the floor exactly. Covered by API +
  engine tests.

**(b) Pacing & budget utilization (success #3 surfaced).** Each `RecLine` now carries
`daily_cap`, `current_utilization`, `recommended_utilization`, and a derived `pacing_flag`
∈ {`scale_opportunity`, `capped_constrained`, `waste_risk`, `healthy`} (see (d) for why four,
not three). A campaign at ≥ `HIGH_UTILIZATION` (0.90 of its cap) and above its hurdle and free
to scale is an efficient winner *leaving revenue on the table*; below the hurdle it is
*burning its full budget*. The threshold is a **display/derived constant in
`engine/recommend.py`, deliberately NOT in `config.py`** (it changes no numeric decision and so
stays out of the fingerprints). New UI: a "Pacing & budget utilization" panel (per-campaign cap
bars, current → recommended) and a reserve KPI that reports mode + reserve share.

**(c) Determinism / scope.** Pure optimizer-mode + arithmetic; engine version unchanged
(`stage3.5`) and **fingerprints untouched** (no generated-data or config change). Tests:
`tests/test_pacing.py` (mode superset, tight-floor reserve, optimizer-level
contribution-never-worse, pacing↔hurdle consistency) + API roundtrip/validation in
`tests/test_api.py`. Reserve **modes**, not yet the reserve *feasibility* search over a held
buffer — that and durable approval/marts are later S4 slices.

**(d) Review follow-up (coherence + demo, post-merge).** A review flagged that the first cut
inferred pacing from utilization alone, which let an inventory-blocked, held-flat campaign
(PMax) be labelled `scale_opportunity` — contradicting its own `inventory_no_scale` flag.
Fixed by reconciling the flag with the optimizer's bounds (`engine/recommend.py::_pacing_flag`):
`scale_opportunity` now requires near-cap **and** above-hurdle **and** free to scale; an
equally efficient but inventory-limited campaign is `capped_constrained`; near-cap below the
hurdle stays `waste_risk`. Added a clearly-labelled **"Efficiency stress (4.1×)" demo preset**
(efficiency-first + ROAS floor 4.1) so the reserve lever is visibly exercised without making
4.1 a hidden default. **Deliberately deferred:** richer pacing from an *observable cap-hit
rate* (days where `spend ≈ daily_cap`, derivable from canonical without touching the latent
`_cap_hit` dropped at `generator.py:392`); the current signal is **daily utilization only** and
makes **no intraday-pacing claim** (the synthetic feeds are daily).

## D-028 — Stage 4.3: calibration registry API + platform-vs-calibrated sensitivity
**Stage 4 (trust & business controls).** Exposes the incrementality **calibration registry**
with full provenance and lets the marketer perturb segment coefficients to see how the
**deterministic optimizer** responds — the brief's "platform-reported vs calibrated decision"
story (FINAL_PLAN §6), not a staged reveal.

**(a) Registry module (`decision_engine/calibration/registry.py`).** Loads the synthetic
``calibration_registry`` table (source, effective period, confidence, scope,
``is_synthetic=True`` on every row). ``apply_overrides`` validates segment names and
coefficient bounds `(0, 2]` before merging sensitivity what-ifs onto the approved map.
``engine/data.py`` now sources coefficients through this module (replacing the inline
``_calibration_map`` helper).

**(b) Engine + API wiring.** ``Constraints.calibration_overrides`` (hashable tuple, folded
into ``scenario_id`` via ``ConstraintParams``) rebuilds the modeling panel when non-empty
(bypassing the default cached context) so calibrated revenue, response curves, and the
optimizer all reflect the perturbed coefficients. Each ``CampaignLine`` carries
``incrementality``, ``platform_roas_current``, and ``calibrated_roas_current`` (at current
spend). ``Recommendation.calibration_registry`` returns provenance rows with
``approved_coefficient``, effective ``coefficient``, and an ``overridden`` flag.
- ``GET /api/calibration/registry`` — read-only provenance catalog.
- ``GET /api/recommendation?calibration_overrides={...}`` — JSON segment→coefficient
  overrides, validated before the solver runs.

**(c) UI.** Measured-inspired cross-channel table (Platform ROAS vs Calibrated ROAS + gap),
a provenance card, and per-segment coefficient sliders that re-solve the plan live. The
enforced ROAS floor remains on the **calibrated** lens (D-008); platform ROAS stays context.

**(d) Determinism / scope.** No generated-data or ``config.py`` change → fingerprints
untouched. Tests: ``tests/test_calibration.py`` + API roundtrip/validation in
``tests/test_api.py``. Does not add real lift-study ingestion or a durable registry write
path — overrides are scenario inputs only (Stage 4.4 audit store is next for persistence).

**(e) Safety pass (review follow-up).** A review flagged that a feasible plan with active
sensitivity overrides could still be approved — making a what-if coefficient look
registry-approved. Hardened so a **sensitivity scenario is never approvable**:
- ``Recommendation.is_sensitivity_override`` (True iff any override active); approval returns
  **422** for such a scenario (Reject still allowed), alongside the existing infeasible-422.
- Honest disclosure: a "Sensitivity scenario — not registry-approved" badge + banner stating
  **"forecast and response models were re-estimated under alternate calibration coefficients"**
  (the historical calibrated-revenue series is recomputed, not just the headline KPI — we do
  the *re-estimation* interpretation, not a fixed-fits perturbation, and say so).
- ``calibration_fingerprint`` (fingerprint of the **approved** registry) is pinned on the
  immutable snapshot so a stored sensitivity result (base registry + recorded overrides) is
  reproducible; an override does not change it (overrides are never written to the registry).
- The optimizer's enforced floor stays the **calibrated** blended ROAS; platform ROAS is
  comparison-only and invariant to the coefficient (unit-tested). The ``0.35 → 0.25`` case is
  tested to go infeasible (calibrated ROAS 3.91 < 4.0) → approve 422.
- Forward note: a *formally approved* calibration revision would be written to the registry as
  a **new version** (then approvable) — distinct from a never-approvable what-if. That registry
  write path is later (with the Stage 4.4 durable store).

## D-029 — Stage 4.2: conformal interval calibration (CQR) for the BAU band
**Stage 4.2.** The XGBoost P10/P90 band materially **under-covers**: pooled held-out
coverage ≈ 0.43 against an 0.80 target (the band is too narrow). This was a disclosed
caveat ("do not lean on the band for risk sizing"). Stage 4.2 corrects it.

**(a) Method.** Conformalized Quantile Regression (Romano, Patterson & Candès 2019),
``backend/decision_engine/engine/intervals.py``. On a held-out **calibration window**
(``t∈[126,161]`` — the harness *val* split, gap-separated from both train and test) we
fit the XGBoost quantiles on ``t≤119``, score each realized value's signed distance
outside its ``[P10,P90]`` band, **level-normalize** the score by ``max(|P50|,1)`` (so
campaigns of very different revenue scale pool into one portfolio offset), and take the
finite-sample ``⌈(n+1)·0.80⌉/n`` empirical quantile. The calibrated band is
``[P10−offset·scale, P90+offset·scale]``, clamped so a (rare) narrowing offset can never
cross the median. Deterministic (fixed-seed, single-threaded XGBoost; pure-numpy quantile).

**(b) Exchangeability — the subtle part.** A first cut calibrated on the campaigns'
*selected* bands (XGBoost for two, trailing-14d **±20%** for the rest). That ±20%
heuristic is wide, so the calibration window read **0.87** coverage while the report's
*test* number (pure XGBoost quantiles) read **0.43** — non-exchangeable, and the fitted
offset made test **worse** (0.25). Fix: conformal targets the **XGBoost quantile band
specifically** (the band that is miscalibrated), pooled identically to what the report
scores as ``quantile_sorted``. Calibration and test windows are then exchangeable (both
≈0.44 raw). Baseline-fallback campaigns keep their ±20% heuristic band and are **not**
conformalized. Result: held-out calibration 0.44→0.81, out-of-sample **test 0.43→0.83**
(verdict ``calibrated``), CQR offset ≈ 0.034.

**(c) Decision invariance.** Calibration widens **only the displayed P10/P90 band**.
The optimizer anchors on the **P50** forward level (÷horizon) and decides on
marginal-ROAS ordering + the ROAS floor — none of which the band touches — so **no
allocation changes**. P50 is never shifted (unit-tested). This keeps the band honest
without making it a covert decision input.

**(d) Wiring.** ``bau_forecast.forecast`` returns ``(forecasts, ConformalCalibrator)``;
each line carries the calibrated ``forecast_p10/p90`` plus raw ``forecast_p10_raw/p90_raw``
for transparency. ``Recommendation.interval_calibration`` surfaces the portfolio offset
and measured raw/calibrated coverage; the forecast chart subtitle states the calibrated
held-out coverage. The report (§4) shows raw **and** calibrated coverage with the offset
and calibration ``n``; ``_interpret`` headlines the calibrated verdict.

**(e) Determinism / scope.** No generated-data or ``config.py`` change → dataset
fingerprints untouched. Tests: ``tests/test_intervals.py`` (offset math, leakage-safe
fit, clamping, out-of-sample coverage lift, XGBoost-only widening, P50 invariance);
``make model-report`` regenerated. Not done here: per-campaign / conditional conformal,
or rolling-origin recalibration (the production-faithful expanding-train folds also show
≈0.44 raw coverage — a single portfolio offset is the Stage-4 slice; finer conditioning is
later).

## D-030 — Provenance & governance hardening (config snapshot, calibration identity, idempotency, baseline coherence, binding/solver, lock)
**Stage 4 (consistency pass).** An external review (Codex, corroborated by GPT)
found the modeling stack sound but the **approval/provenance guarantees not airtight
against contract violations**. None is a model-quality issue; all are governance
consistency. Fixes, in the order applied:

**(a) Immutable engine-config snapshot.** Previously ``config_fingerprint()`` re-read
``config.py`` live while the optimizer consumed import-frozen constants, so a runtime
config edit could move the fingerprint (and scenario id) while the allocation stayed
identical — a plan could claim a config it wasn't running. Introduced a frozen
``EngineConfig`` snapshot (``recommend.engine_config()``, ``lru_cache``) consumed by
**both** the optimizer's floors/movement **and** the fingerprint. A config change now
takes effect only on restart (cache clear), and when it does the consumed values and
the fingerprint move **together**. Tests: a runtime mutation changes neither the
fingerprint nor the consumed floor (no false re-versioning); a restart changes both.

**(b) Approved-calibration-registry identity.** The approved registry fingerprint now
participates in the **scenario id**, the **stale guard** (``engine_provenance``), the
**snapshot**, and the **audit**. A registry revision — including a provenance-only one
whose coefficients (and thus ``data_fingerprint``) are unchanged — makes older pending
plans stale and yields a new scenario id. Added a derived
``effective_calibration_fingerprint = hash(approved registry + normalized overrides)``
recorded on the recommendation and the decision. Sensitivity overrides remain
non-approvable (D-028e); this separates *what-if* (never approvable) from an *approved
registry revision* (a future new registry version).

**(c) Idempotent terminal decisions.** A recorded decision is immutable: replaying the
same action returns the stored decision (200) and a conflicting action returns 409 —
**regardless of later supersession or state drift**. The terminal-state replay now runs
**before** the stale/supersession guards, fixing a case where re-confirming an
already-approved plan 409'd once a newer scenario existed.

**(d) Baseline-selection coherence (M2).** The selector compared XGBoost against a
per-fold *oracle mix* of baselines but always deployed trailing-14d. It now returns the
**exact champion** (``xgboost_quantile`` | ``baseline_trailing_14d`` |
``baseline_same_weekday``): the single pooled-lower-WAPE baseline is both the comparison
baseline and the deployed fallback, used identically by the live forecast, the report,
and the optimizer's level anchor. This shifts a few campaigns from trailing-14d to
same-weekday where same-weekday is the true champion (report regenerated; dataset
fingerprints unaffected — selection is an engine concern, not generated data).

**(e) Binding report + solver status.** The budget line is now mode-aware: growth shows
``budget_fully_deployed`` (binding when fully deployed); efficiency-first shows
``budget_ceiling`` with deployed/ceiling/**reserve**/slack-to-ceiling (binding only when
reserve ≈ 0) — fixing a fully-deployed budget mislabeled as slack. The SLSQP terminal
status (success/status/message/iterations) is surfaced, and the full binding report is
persisted in the **audit** record.

**(f) Dependency lock.** ``matplotlib`` (declared in ``pyproject.toml`` for
``make model-report``) was missing from ``requirements-lock.txt``, so the report failed
from a clean locked install. Added ``matplotlib`` + its transitive deps (contourpy,
cycler, fonttools, kiwisolver, pillow, pyparsing) pinned to the tested versions. None of
numpy/pandas/scipy changed → committed dataset fingerprint unaffected.

**(g) Docs.** README updated: champion-baseline wording, the 80% band is now described
as conformal-(CQR)-calibrated (≈83% held-out vs 80% target, display-only), and Stage 4.1/
4.2/4.3 marked done with the provenance-hardening note. UI surfaces the solver status in
"Why this plan" and the calibrated-band coverage in the forecast subtitle.

**Impact.** Engine, API (schemas/recommendation/main/store), selection, optimizer,
bau_forecast, harness, frontend types/UI, lock, README. New/updated tests in
``test_api.py`` (config snapshot consistency, registry-revision staleness, effective
fingerprint, idempotent-after-supersession), ``test_pacing.py`` (solver status + reserve
binding), ``test_engine.py`` (three-model anchor). All gates green.

## D-032 — Looker-ready SQL marts over the audit ledger (Stage 4.5)
**Stage 4 (Looker-ready marts).** Added a lightweight BI layer over the durable
ledger (D-031) as plain SQL **views** — no warehouse, no extra dependency, always
fresh. DDL is the committed source of truth in `backend/api/marts.py`; four
single-grain marts flatten the ledger's JSON columns via SQLite JSON1:
- `mart_decision` — one row per decision: scalar provenance + flattened
  constraint/solver params + JSON rollups (campaign count, deployed spend, count of
  binding/slack/violated portfolio constraints, sensitivity-override flag).
- `mart_decision_line` — one row per (decision, campaign): recommended spend +
  within-decision spend share.
- `mart_binding_constraint` — one row per (decision, portfolio constraint): name +
  binding/slack/violated status + detail.
- `mart_audit_chain` — provenance + `prev_hash`/`row_hash` linkage for governance.

**Surface.** Views are created alongside the ledger on store init, so they exist
wherever the DB does. `GET /api/marts` (name → row count) and `GET /api/marts/{name}`
(whitelisted) expose them; `scripts/build_marts.py` / `make marts` materialize the
DDL + a CSV extract per mart to `reports/marts/` (gitignored, reproducible). A Looker
deploy points LookML at the same `marts.sql` views.

**Scope.** Marts cover the **decision/governance grain** — what was decided, how it
was allocated, under which constraints, and with what provenance — sourced from the
immutable ledger. Forecast KPIs (expected revenue, reserve) live in the recommendation
snapshot, not the audit record, so they are intentionally out of scope here.

**Impact.** New `backend/api/marts.py`, `scripts/build_marts.py`, `make marts` target;
`backend/api/store.py` (auto-create views + `mart`/`export_marts`), `backend/api/main.py`
(`/api/marts` endpoints), `frontend/lib/api.ts` already carries the audit bindings.
Tests: `tests/test_marts.py` (grain, rollup reconciliation to line facts, binding match,
chain↔ledger equality, DDL stability, export). All gates green (225 tests, fingerprint
unchanged — marts add no `config.py` constant).

## D-031 — Durable, append-only, hash-chained audit ledger (Stage 4.4)
**Stage 4 (durable approval/audit).** The decision/audit store was in-memory
(`DecisionStore`), so approvals were lost on restart — incompatible with the
"every decision is auditable" thesis (`FINAL_PLAN.md:43, 232`). Replaced it with
`DurableDecisionStore` (`backend/api/store.py`), persisted to SQLite via the stdlib
`sqlite3` (no new dependency).

**Design.**
- **Append-only + tamper-evident.** Each decision is one immutable row; a hash chain
  commits `row_hash = sha256(prev_row_hash + canonical_payload)` over the full D-030
  provenance (constraints, allocation, data/config/calibration/effective fingerprints,
  binding, execution events). `GET /api/audit/verify` recomputes the chain and reports
  integrity; `GET /api/audit/log` returns the ordered ledger (also the read source for
  the Stage 4.5 marts). DB triggers `RAISE(ABORT)` on any `UPDATE`/`DELETE`, so the
  normal mutation paths are blocked and direct-file tampering is still caught by the
  chain (`verify_chain` returns the first broken `seq`).
- **Contract preserved.** First-write-wins, idempotent replay of the same action,
  `DecisionConflict` on a conflicting action, and terminal immutability are unchanged
  from D-030 — the durable store is a drop-in for the API (`decide`/`status`/`get`).
- **Scope.** Snapshots stay in-memory (bounded LRU): they are recomputable scenario
  candidates and each decision row already copies the snapshot's provenance, so the
  audit is self-contained even after a snapshot is evicted. Only *decisions* are durable.
- **Config.** DB path `data/audit/decisions.db` (gitignored), overridable via the
  `TC_AUDIT_DB` env var; `":memory:"` gives an isolated per-test ledger. No `config.py`
  scenario constant changed → dataset/config fingerprints untouched.

**Impact.** `backend/api/store.py` (new durable store + shared response/record helpers),
`backend/api/main.py` (store wiring + `/api/audit/log`, `/api/audit/verify`),
`backend/api/schemas.py` (`AuditChainStatus`), `.gitignore`, `frontend/lib/api.ts`
(typed bindings). Tests: `tests/test_audit_store.py` (restart persistence, idempotent
replay/conflict, append-only triggers, chain verification + tamper detection); the API
test fixture now exercises the durable backend (`:memory:`). All gates green.

## D-034 — `realistic` dataset profile (structured volatility + exogenous spend variation)
**Stage 4 (trust/robustness).** The committed golden dataset is deliberately
smooth: narrow spend support, ~5% revenue noise, two promo windows. That makes a
clean known-truth benchmark but is *unrealistic* — real paid-media data is volatile,
seasonal, and (worse) mostly observational, so a credible demo must show how the
engine behaves on messy data. The volatility stress test (D-033) confirmed the
forecast degrades gracefully but per-campaign marginal recovery is fragile without
identifying spend variation.

**Decision.** Add a second **deterministic** dataset *profile*, `realistic`,
alongside `golden`, selected via `TC_DATASET_PROFILE` (default `golden`). Both
profiles share the **same latent truth** (`synth/scenario.py` Hill/incrementality),
so known-truth grading stays valid; they differ only in the **observable driving
process**. Golden remains the pinned regression anchor; realistic is pinned
separately (its own fingerprint) so its reproducibility is guarded without making
it the benchmark.

**Profile abstraction (swap path).** `config.profile_paths()` roots each profile's
data: `golden` → the legacy `data/{raw,canonical,internal}` (bytes untouched →
fingerprint unchanged), `realistic` → `data/realistic/…`. `generate(seed, profile)`,
`persistence.write_all(profile=…)`, and the generate CLI (`--profile`) resolve dirs
at call time, so generating one profile can never overwrite another's. Promoting
realistic to the default later is a one-line change to `DATASET_PROFILE`; the
module-level path constants and the engine/API/ingestion follow it automatically.

**What `realistic` adds (identifiability-preserving).**
- **Structured signal:** stronger asymmetric weekly shape, annual seasonality
  (±12%), and more/larger promo + holiday windows.
- **Exogenous spend variation:** a *mix* — three campaigns ran staggered
  ±15/±30% budget experiments (deterministic step schedule + short adstock
  washouts) **uncorrelated with demand**; the rest stay purely observational. This
  is the design point: campaigns with identifying variation recover marginals well,
  observational ones don't.
- **Heteroscedastic, mean-preserving revenue noise** (noisier at low utilization)
  + sparse two-sided shocks, kept below the identifiability-break point.

**Determinism.** Realistic volatility is drawn from an INDEPENDENT child stream
(spawn path `1000+i`), so the golden draw sequence — and its pinned fingerprint
(`aa27fe98…`) — are byte-for-byte unchanged. Realistic is itself reproducible:
canonical `66b5dd59…`, full-artifact `a76446919b…` (pinned in
`tests/test_fingerprints.py`). All 13 canonical tables stay schema-valid and all
11 planted defects survive unchanged.

**Observed (engine on realistic, end-to-end).** revenue CV 0.23 (golden 0.08),
selected forecast WAPE ≈ 0.11, held-out conformal P10–P90 coverage ≈ 0.85
(target 0.80), response Spearman ≈ 0.96. The three experimental campaigns recover
marginal ROAS with |error| ≈ 0.4 vs ≈ 1.3–2.0 for observational ones — the
project's central thesis ("you need spend variation to identify causal response"),
now visible in the data.

**Impact.** `config.py` (profile roots + resolvers), `synth/generator.py`
(profile-threaded calendar/simulation + experiment design), `synth/persistence.py`
(profile-resolved write dirs), `scripts/generate_synthetic_data.py` (`--profile`),
`Makefile` (`generate-realistic`), `.gitignore` (`data/realistic/`),
`tests/test_fingerprints.py` (realistic pin + schema test). Golden gates unchanged.

## D-035 — `realistic` promoted to PRIMARY data; `golden` is now the benchmark only
**Stage 4.** Following D-034, the `realistic` profile passed its gates — it is
deterministic and separately pinned, all 13 canonical tables stay schema-valid,
all 11 planted defects survive, and the engine runs end-to-end with believable,
honest numbers (test WAPE ≈ 0.11, held-out conformal P10–P90 coverage ≈ 0.85,
response Spearman ≈ 0.96; experimental campaigns recover marginals at |err| ≈ 0.4
vs ≈ 1.3–2.0 observational). Real paid-media data is volatile and mostly
observational, so the demo/app should run on the messy regime where the
guardrails and abstention actually matter.

**Decision.** Flip the default dataset profile to `realistic` — it is now the
PRIMARY data the engine, API, and model-performance report use. `golden` stays a
first-class profile but only as the **deterministic regression benchmark**.

**Mechanics.**
- `config.DATASET_PROFILE` default → `realistic` (still overridable via
  `TC_DATASET_PROFILE`). The module path constants + engine/API/ingestion/report
  follow it automatically.
- **The test suite is hard-pinned to golden** (`tests/conftest.py` sets
  `TC_DATASET_PROFILE=golden` before importing any backend module), so golden
  remains the deterministic anchor regardless of the runtime default. Tests that
  exercise realistic pass `profile="realistic"` explicitly (env-independent).
- `scripts/verify_fingerprint.py` now verifies BOTH profiles against their pins.
- `make generate` writes BOTH datasets to disk (realistic primary + golden
  benchmark); `make generate-realistic` / `make generate-golden` do one each;
  `verify-clean-install` generates both before the (golden) suite; `make clean`
  also clears `data/realistic`.
- The primary model-performance report (`reports/model_performance`) is now
  generated from realistic (`data_fingerprint 66b5dd59…`).

**Guarantees.** No `config.py` scenario constant changed. Golden's pinned
fingerprint (`aa27fe98…`) is byte-for-byte unchanged; realistic stays pinned
(`a76446919b…`). Full suite green. Golden physically remains at
`data/{raw,canonical}` and realistic at `data/realistic/`; a symmetric `data/golden`
rename is an optional, fingerprint-safe follow-up.

## D-036 — Rebalanced report plots toward decision/causal diagnostics
**Stage 4.** The model-performance report computed 10 sections but all 9 plots only
visualized forecast point error / residuals (§3/§7). The three sections that carry
the project's thesis — §8 response recovery (estimated vs latent marginal ROAS),
§4 interval calibration (raw → conformal), §9 optimizer sensitivity — were
table-only. For a *decision* engine that's the wrong emphasis.

**Decision.** Rebalance to **8 plots** (`backend/decision_engine/eval/plots.py`):
- **Forecast (4):** `01_actual_vs_predicted`, `02_residuals_vs_predicted`
  (heteroscedasticity — now a real signal on the realistic profile),
  `03_error_by_campaign`, `04_forecast_fan`.
- **Decision/causal (4, new):** `05_marginal_roas_recovery` (estimated vs latent
  marginal ROAS, 45° line, scale-floor boundary, in-support vs extrapolation
  markers, downside whiskers — the identifiability money-shot),
  `06_interval_reliability` (raw → conformal P10–P90 coverage vs the 0.80 target
  + mean widths), `07_optimizer_sensitivity` (blended ROAS under ±10/20% marginal
  error vs the ROAS floor; markers flag feasibility, colour flags direction
  stability), `08_allocation_recommendation` (current vs recommended spend).
- **Dropped:** residuals-over-time, residuals-vs-spend, residual distribution,
  error-by-day-of-week (flat by construction — the target is a 7-day *sum*),
  error-by-spend-band.

**Two correctness fixes folded in.** (1) The forecast fan previously drew the
**raw** XGBoost band (unlabeled), which is why actuals fell outside it; it now draws
the **conformal-calibrated** band (with the raw band as a dotted reference) and prints
the empirical coverage. (2) `07` does not call infeasible scenarios "blocked" — the
optimizer still returns those plans; the marker honestly distinguishes
feasible/infeasible from direction-stable/flipped.

**Mechanics.** `generate_plots(report, test_frame, out_dir, recommendation)` is now
fed from the report dict (response/sensitivity/quantile) plus the live
`EngineRecommendation` (scale floor + allocation); `report.py` builds the
recommendation (deterministic, NOT written to `metrics.json`). Stale PNGs are cleared
on regen. The latent-marginal chart is eval/report-context only (already used for §8
grading), never a model input.

**Guarantees.** `metrics.json` is byte-identical across two runs; full suite green.

**Surfaced finding (now resolved in D-037).** On first generation the realistic
*primary* plan was `feasible=False`: it missed the prospecting-share floor
(`PROSPECTING_MIN_SHARE = 0.33`) by ~1pp (0.3192). That constant was calibrated for
golden's caps. D-037 makes the floor profile-aware (the prospecting daily caps impose
a cap-implied ceiling that differs by profile), so the realistic plan is now feasible
and the daily caps are the honestly-reported active constraint.

## D-037 — Prospecting floor is profile-aware (cap-implied ceiling differs by profile)
**Stage 3/4 · policy knob.** *Decision:* `PROSPECTING_MIN_SHARE` is now resolved
per dataset profile via `config.prospecting_min_share(profile)` —
`{golden: 0.33, realistic: 0.30}` — instead of a single golden-calibrated constant.

*Why.* The prospecting campaigns cap out early (high utilization by design), so their
daily caps impose a **cap-implied ceiling** on prospecting share in growth
(full-budget) mode. On golden that ceiling is ~0.335, so the 0.33 floor still BINDS
(the active guardrail). On the realistic profile the caps **plus** the below-hurdle
no-increase gate on `META_ADV_SHOPPING` pin prospecting at ~0.319 of the
volatility-/trend-inflated budget — so a 0.33 floor is **physically infeasible** in
growth mode (it isn't a model error; the budget equality + caps make 0.33 unreachable).
The realistic floor is set to **0.30**, a defensible brand-investment minimum below the
~0.319 ceiling: the plan is feasible with margin, and the prospecting **daily caps**
(not the policy floor) are the honestly-reported active constraint.

*Consequences.*
- Realistic `expected` plan is now `feasible=True` (blended ROAS ~4.20× vs 4.00× floor);
  **all** ±10/±20% marginal-error perturbations are now feasible AND direction-stable
  (previously every perturbation tripped the infeasible 0.33 floor).
- The sensitivity caveat and §9 narrative in the report are now **data-driven** (they
  describe whichever perturbations — if any — are infeasible, rather than a hardcoded
  "−20% haircut tips infeasible" sentence calibrated to golden).
- `unstable_only_when_infeasible` is now vacuously `True` when no perturbation flips
  direction (the previous boolean returned a misleading `False` in the all-stable case).

*Not a fingerprint change.* `PROSPECTING_MIN_SHARE` is an **optimizer policy knob**, not
a generator input, so the data fingerprints (golden + realistic) are untouched. The
golden-pinned suite still asserts the 0.33 floor holds; a new
`test_prospecting_floor_is_profile_aware` guards the per-profile values and the realistic
floor staying below its ~0.319 ceiling. `metrics.json` remains byte-identical across runs.

## D-038 — Report scores the DEPLOYED forecast; marts re-stamped to the active profile
**Stage 4 · report/marts honesty.** Four consistency fixes after an external review of
the generated artifacts:

**(a) Forecast fan + interval metrics center on the SELECTED champion (bug fix).** The
eval previously built the fan and the pooled interval coverage from XGBoost quantiles
for *every* campaign — even ones whose champion (from the frozen pre-test selector) is a
baseline. So the fan could show XGBoost's P50 for a baseline-champion campaign,
contradicting the §3 table and the live engine. `build_test_frame` now mirrors
`engine/bau_forecast.forecast` exactly: XGBoost champions get the conformal-widened
quantile band; baseline champions get their point + the deployed ±20% band (so
`p50 == pred`). The fan prefers the best-WAPE XGBoost champion (to illustrate the
conformal band). A new **deployed-interval** metric (`deployed_interval_metrics`) reports
the coverage/width of the band the engine *actually* serves per champion, split by model
— the honest interval figure, distinct from the XGBoost-quantile-only conformal
diagnostic (which is retained and relabeled). Plot 06 now shows raw → conformal →
deployed.

**(b) Marts re-stamped to the realistic profile.** The committed `reports/marts/*.csv`
were exported from a stale golden-era ledger row (floor 0.33, fingerprint `3f898…`).
`scripts/build_marts.py` now seeds a **dedicated, reproducible demo ledger**
(`data/audit/demo_marts.db`) with the current active-profile recommendation if empty,
then exports + writes `reports/marts/MANIFEST.json`. The manifest carries BOTH the
**panel fingerprint** (what the ledger stores) and the **canonical-tables fingerprint**
(the report headline) so the marts and the model report provably describe the same
profile — they otherwise look mismatched because they are different hashes by design.

**(c) Prospecting-share transparency.** The report now emits a §10 "Decision feasibility
& constraint posture" with the exact prospecting computation (numerator campaigns,
numerator/denominator, actual share, floor, slack, binds?) — e.g. realistic
`30.09% vs 30.00% → +0.09pp (binds)` — so the green feasibility is self-explanatory and
matches `mart_binding_constraint`.

**(d) Post-selection holdout drift, split demo-safety, WAPE-first wording.** Interpretation
now surfaces XGBoost champions that **regressed >25% vs a baseline on the untouched test**
(e.g. `GOOGLE_PMAX`, `META_RETARGETING`) as a retraining signal — deliberately NOT flipped
(flipping would leak test into the policy); a 25% (not 5%) threshold avoids flagging
near-ties. The single `safe_for_demo` flag is split into `safe_for_model_demo` (forecast +
response fidelity) and `safe_for_decision_demo` (feasible, direction-stable plan), and the
headline leads with WAPE (the ~accuracy% is labeled an intuitive gloss only). The interval
verdict wording is softened (85–87% is "slightly conservative", not "broken").

**(e) Review follow-up — honest interval labeling + non-cherry-picked fan + gates.**
A second external pass raised valid presentation points (and one invalid invariant):
- **Mixed-policy interval labeling.** The deployed 87.2% is now described as *empirical
  mixed-policy coverage* (conformal XGBoost band **+** an operational ±20% **heuristic** for
  baseline champions), never as "the conformal 80% interval". The 0.80-target calibration
  verdict is reserved for the XGBoost conformal band (85.1%, "slightly conservative"). The
  Next.js forecast-band subtitle is corrected the same way (it previously claimed
  "conformal-calibrated (XGBoost)" for every bar, including baseline-champion ±20% bars).
- **Fan campaign is chosen by a fixed business criterion, not test WAPE.** Plot 04 now
  shows the highest **current-spend** XGBoost champion (`GOOGLE_NONBRAND`, the main
  room-to-scale channel and the one campaign where XGBoost materially beats its baseline),
  so the illustrative fan is not selected on the metric it illustrates. (An interim
  test-window-spend rule wrongly surfaced a *drifting* champion; current-spend fixes it.)
- **Corrected invariant.** The reviewer asked to assert `test-frame P50 == live API P50`
  per campaign. That is **wrong by design**: the eval frame is a holdout (trained on
  pre-test rows, scored on the test window) while the live forecast predicts the current
  operating point trained on all mature rows — the numeric P50s differ for every campaign
  and *should*. The correct, now-tested invariant is **model-choice identity**: the eval
  frame, the pooled forecast, and the live engine all serve the SAME selected champion per
  campaign, and the eval frame is centered on it (`p50 == pred`).
- **Gates added.** `scripts/build_marts.py` fails generation if the marts' canonical
  fingerprint ≠ the model report's headline fingerprint (stronger than the manifest).
  `tests/test_report_consistency.py` adds the per-campaign model-identity gate, the
  report↔mart fingerprint reconciliation (panel vs canonical, different by design), and a
  check that baseline-champion bands are the ±20% heuristic (not conformal).

*Deferred (documented, not done).* Split-conformal residual intervals around baseline
champions would let every served band target a single nominal 0.80 — a genuine future
improvement, but it changes the deployed band and is out of scope for a consistency/
labeling pass. Per the review, we did NOT tune XGBoost for the drifting PMax/Retargeting,
touch the generator, re-use the holdout to re-pick models, or move the 0.30 floor.

*Not a fingerprint change.* No `config.py` constant moved; `metrics.json` remains
byte-identical across runs (the marts manifest/CSVs carry a wall-clock `generated_at`/
`decided_at` by design and live under the gitignored `data/audit/` demo ledger). New guards
`test_deployed_interval_metrics_pool_and_split_by_model` and `tests/test_report_consistency.py`;
full suite green.

## D-046 — Web UI folder renamed `true-classic/` → `frontend/`
**Stage 4, UI track (cosmetic/structural — no behaviour change).** The Vite + React SPA
introduced in D-043 lived in `true-classic/`. That name was ambiguous (a folder literally
named `true-classic/` inside the True Classic repo reads like "the True Classic part" when it
is just the web client) and non-conventional. Renamed the directory to `frontend/` — the
conventional name, freed up when the retired Stage-1 Next.js `frontend/` was deleted (D-043).

**What changed.**
- Moved the directory `true-classic/` → `frontend/` (the files were untracked, so this is a
  plain move, not a `git mv`; no history to preserve).
- Updated every folder-path reference: `Makefile` (`make web` / `web-setup` now `cd frontend`),
  `.gitignore` (`frontend/dist/`), `.env.example`, `README.md`, `CLAUDE.md`, `AGENTS.md`,
  `docs/PROJECT_REPORT.md`, and the live component paths in D-044/D-045 above.
- **Not changed:** the Python package name `true-classic-paid-media-decision-engine`
  (`pyproject.toml`) and the brand asset `public/logos/true-classic-wordmark.svg` — these are
  not the folder. The earlier D-043 narrative keeps its historical `true-classic/` references
  (it describes the state at that time); this entry supersedes the path.
- `docs/UI_INTEGRATION_MAP.md` is a pre-migration Stage-1 design doc (it still frames the
  production frontend as the old Next.js `frontend/`); left as-is, historical.

**Risk / impact.** None functional. No engine/API/data/fingerprint changes; `make test`
unaffected. Internal imports are relative, so the app builds and `make web` runs unchanged
apart from the directory name.

## D-045 — Model Evidence Phase D: row-level untouched-test predictions + interactive forecast-vs-actual charts
**Stage 4 (trust & business controls), UI + API track.** Promoted the Model Evidence tab from
aggregate-only (D-044 Champion Selection bars) to **row-level forecast accuracy**, so the
brief's M2 "how much to trust the output" beat is *visible in-app* rather than only as static
report PNGs. The accuracy diagnostics (`01_actual_vs_predicted`, `04_forecast_fan`) already
existed as `reports/model_performance/plots/*.png`, but the underlying per-row predictions were
drawn in-memory during report generation and discarded — `metrics.json` carried aggregates only.

**What changed.**
- **Persisted artifact** `reports/model_performance/test_predictions.csv` (`eval/report.py`
  `_write_test_predictions`). It is exactly the tidy `build_test_frame` rows the PNGs already
  draw from: per campaign × untouched-test day — `date`, realized `y` (holdout label), `pred`
  (== selected champion P50), the **deployed** band (`p10/p50/p90`, conformal for XGBoost
  champions / ±20% heuristic for baseline champions), `p10_raw/p90_raw`, `residual`, `model`.
  **No latent generator-truth** (no marginals/incrementality) — these are holdout actuals +
  predictions, so exposing them carries no target-leakage risk (unlike `latent_marginal_eval_only`,
  which stays omitted). Fully deterministic; report numbers are byte-identical (WAPE 0.11098).
- **Endpoint** `GET /api/model-evidence` bumped to **`model-evidence.v2`**: each campaign now
  carries `test_series` (`ForecastSeriesPoint[]` with a per-row `covered` flag) + `test_coverage`,
  and the response carries `series_available`. The service reads the CSV with stdlib `csv` (no
  pandas in the API path); when the file is absent (a report predating the artifact) it returns
  `series_available=False` and the UI falls back to bars — backward compatible.
- **Interactive charts** in `ModelEvidence.tsx` (hand-rolled SVG, matching `ForecastResponse.tsx`):
  a per-campaign **Forecast vs actual over time** fan (P10–P90 band, P50 champion line, actuals
  coloured in/out of band, hover tooltip) and an **Actual vs predicted** scatter (45° perfect
  line, points coloured by band coverage). Drives the contrast beat directly: GOOGLE_PMAX (drift)
  shows actuals riding above the band and points off the diagonal; GOOGLE_NONBRAND (XGBoost's
  material win) clusters tight on the diagonal at 94% coverage.

**Risk / impact.** Still **read-only** and deterministic; no engine/optimizer/config changes, so
the data/fingerprint contract is untouched (`make test` green — 266 passed). `metrics.json` gains
an `artifacts.test_predictions` pointer and the new CSV is written by `make model-report`. This
closes the Phase D item explicitly deferred in D-044. Remaining deferred (Phase E): residual
explorer, calibration & latent marginal-recovery workbenches, optimizer perturbation UI, CM-floor
sweep UI, CSV downloads, browser-triggered report regeneration.

## D-044 — Buyer & Inventory tab + Model Evidence tab (Champion Selection v1) + two read-only API routes (Stage 4 scope addition)
**Stage 4 (trust & business controls), UI + API track.** Closed the two remaining
brief-mandated demo beats and laid the provenance-gated model-evidence foundation, phased so
the vertical slice stayed runnable at each step. **Scope addition** to the plan (two new tabs +
two read-only routes), recorded here per `CLAUDE.md`.

**What changed.**
- **`GET /api/inventory`** (`backend/api/inventory_service.py`, schemas `BuyerInventoryItem` /
  `BuyerInventoryResponse`). Surfaces the canonical `fact_inventory_snapshot` (units on hand,
  daily demand, days of cover, lead/safety days, stockout risk) joined to the campaigns each SKU
  sells, plus a deterministic, documented reorder suggestion. The SKU→campaign linkage and the
  `no_scale` flag are read from the engine's own `_context()` (`sku_of` + the `stockout_risk`
  set), so the buyer view and the recommendation's `inventory_no_scale` risk flags can never
  disagree. Derived policy (documented in the payload): `estimated_stockout_date` =
  snapshot_date + floor(days_of_cover); `reorder_qty` = max(0, ceil((lead+safety)×demand −
  on_hand)), **explicitly assuming incoming/open POs = 0**; `urgency` = urgent / reorder_soon /
  monitor from days-of-cover vs the lead+safety threshold. New web tab `ActiveTab.BuyerInventory`
  (`frontend/src/components/BuyerInventory.tsx`) — a single planner card per SKU, **not** a
  second inventory product. (TC-JOG-BLK / Google PMax is the urgent stockout that pins PMax.)
- **Decision Overview scorecard consolidation** (labeling, not a rebuild): the flat KPI row is
  now an explicitly ranked success-criteria scorecard — **Primary outcome** (CM ROAS + net
  contribution/day), **Policy guardrails** (calibrated ROAS floor, **NC-CPA ceiling** — the
  previously-missing actual-vs-target line, prospecting floor), each with a within/binding/
  violated chip read straight from the solver's binding report, and **Context** (spend, reported
  ROAS, reserve). The inventory/strategy exceptions stay in the existing Active Constraints &
  Risks panel.
- **`evidence_input_fingerprint`** (`backend/decision_engine/eval/provenance.py`, stamped into
  the model report's provenance via `eval/report.py`). One comparable hash of the report's
  MODELING-INPUT identity: dataset profile + the recommendation's **panel** data fingerprint +
  config fingerprint + approved-calibration fingerprint + engine version + a new `REPORT_VERSION`.
  It deliberately **excludes any wall-clock timestamp** — the curated endpoint compares it to the
  *live* engine identity to decide fresh-vs-stale, so it must be reproducible from current state
  (a timestamp would make a fresh report read as perpetually stale). The report's headline
  `data_fingerprint` stays the **canonical-tables** hash (mart reconciliation, D-038); the
  evidence fingerprint uses the **panel** hash because that is the identity the recommendation /
  ledger carry, so the two sides are comparable. The helper lives in its own light module so the
  API can recompute the identity without importing matplotlib/the report stack.
- **`GET /api/model-evidence`** (`backend/api/model_evidence_service.py`, curated schema
  `ModelEvidenceResponse`). **NOT** a passthrough of `metrics.json`: a versioned
  (`model-evidence.v1`) view exposing only Champion Selection v1 — provenance, a fresh/stale
  verdict (report `evidence_input_fingerprint` vs the live one), summary, and per-campaign
  selection + untouched-test evidence. Latent generator-truth (`response.*.latent_marginal_eval_only`,
  `sensitivity.*.latent_eval_only`) is omitted by construction. `generated_at` is the report
  file's mtime (kept out of the deterministic report body).
- **Model Evidence tab** (`ActiveTab.ModelEvidence`, `frontend/src/components/ModelEvidence.tsx`).
  Champion Selection v1 only, respecting the pre-test vs test split exactly: a **pre-test
  selection** panel (two bars — XGBoost candidate vs best baseline — improvement %, fold wins,
  5% threshold, the selector's human reason; per-baseline pre-test scores are not persisted) and
  a **separate untouched-test** panel (all three models' test WAPE + champion + holdout-drift
  flag) that is never mixed into the selection chart. Header badges: dataset profile, evidence
  fingerprint, engine version, fresh/stale, synthetic-data disclaimer. Lead walkthrough: Google
  PMax (promoted on pre-test folds, regressed on the untouched test, flagged for retraining and
  **not** retroactively switched — flipping on test would leak the test set into the policy).

**Risk / impact.** Both new routes are **read-only** and deterministic; no engine/optimizer or
config-constant changes, so the data/fingerprint contract is untouched (`make test` unaffected;
`test_report_consistency.py` still passes — the report headline `data_fingerprint` is unchanged).
The report now carries additional provenance keys + the evidence fingerprint, so `metrics.json`
was regenerated. The Model Evidence page is **interactive for exploration, read-only for
methodology** — nothing in it re-picks a model. Deferred (Phase D/E): row-level `test_predictions`,
forecast fan / residual / actual-vs-predicted explorers, calibration & latent marginal-recovery
workbenches, optimizer perturbation UI, CM-floor sweep UI, CSV downloads, browser-triggered report
regeneration.

## D-043 — Web UI migrated from the Stage-1 Next.js shell to a Vite + React SPA (`true-classic/`)
**Stage 4 (trust & business controls), UI track.** The original Stage-1 client (D-021) was a
hand-rolled **Next.js** app-router page under `frontend/`. We have replaced it with a
higher-fidelity **Vite + React 19 + Tailwind v4** single-page app in `true-classic/` (the
Vite UI prototype, wired tab-by-tab to the live API across the recent integration slices).
The Next.js app is now **retired and deleted**.

**Why.** The product needed five governance workspaces (Decision Overview, Data Unification,
Forecast & Response, Budget Planner with a draft→Recompute constraint editor, and an
append-only/hash-chained Audit & Business Controls ledger) plus an execution-payload preview.
The Vite SPA already had the design system and component shell for all of this; finishing it
was cheaper and far better-looking than re-building the same surfaces in the Next.js page. The
Vite app is a strict **superset** of the retired page (which only covered the single
recommendation review/approval view + a separate ingestion page).

**Deviation from the pinned stack.** `CLAUDE.md`/`AGENTS.md` previously named the stack as
**Next.js + FastAPI**. That hard rule existed to forbid a Streamlit-style substitute and keep a
real TS/React client over the API — *not* to mandate Next.js specifically. The replacement is
still **TypeScript + React over the same FastAPI backend**, so the intent is preserved; we drop
SSR/app-router (never used — the client is a thin read-and-govern layer, no server components,
no server actions). `CLAUDE.md`/`AGENTS.md` are updated to say **Vite + React (no Streamlit
substitute)**.

**What changed.**
- `frontend/` (Next.js) **deleted**; `make web` / `make web-setup` now target `true-classic/`
  (`npm install` + `npm run dev`, Vite pinned to **:3000** to match the backend CORS allowlist).
- Stripped the the UI prototype's generated scaffolding: removed the dead
  an unused GenAI scaffolding dependency (never imported) and the unused generated deploy deps
  (`express`/`dotenv`/`tsx`/`@types/express`), deleted `metadata.json` (GenAI capability
  manifest), de-branded `README.md`/`.env.example`/`index.html` title/`vite.config.ts`
  comments.
- Removed the prototype's leftover **mock simulation layer** (`src/fixtures/mockData.ts` and the
  dead state/handlers in `App.tsx`: fake campaigns, scenario history, toast simulator,
  `handleRecalculate`/`handleApprovePlan`, etc.) — every surface now reads the live engine via
  `RecommendationContext`. `src/types.ts` trimmed to the `ActiveTab` nav enum.
- Added an honest **live engine status** strip to the sidebar (backend connection + active
  scenario feasibility + policy), replacing any implied "system health" decoration.

**Risk / impact.** No backend or engine changes; the deterministic data/fingerprint contract is
untouched (`make generate && make test` unaffected). The web client has no automated test gate
beyond `npm run lint` (`tsc --noEmit`), unchanged from the Next.js setup. CORS still allows
:3000 (pinned) and :3001 (fallback for a second instance).

## D-042 — Phase 4 read-only CM-floor policy sweep (evidence; no policy change yet)
**Stage 4 (trust & business controls).** Before swapping the enforced gross blended-ROAS
floor for a portfolio **CM-ROAS** floor, we ran a read-only sweep instead of picking a
number. Added an **optional, default-OFF** `cm_roas_floor` to `optimizer.optimize` (and
`Constraints`), an inequality `Σ mᵢ·Rᵢ(bᵢ) ≥ cm_floor·Σbᵢ` surfaced in `_business_conflicts`
and the binding report, plus `scripts/cm_floor_sweep.py` + `make cm-sweep`
(`reports/economics/CM_FLOOR_SWEEP.md/.json`). **No live default, `config.py` constant,
or fingerprint changed** (the parameter is 0.0 everywhere in production).

*Finding — a portfolio CM-ROAS floor is at best a costly, fragile knob; not worth exposing.*
- **Growth: redundant.** With fixed spend (`Σbᵢ=B`) **maximizing net contribution already
  maximizes CM ROAS**, so the achievable CM is pinned at **1.941×**; every floor ≤ that is
  a no-op (identical plan) and every floor above is infeasible — the floor can only reject,
  never reshape.
- **Efficiency-first: actionable but costly** (corrected after a fine boundary scan —
  thanks to a reviewer catch; the coarse grid had straddled the boundary). By withholding
  budget, floors are feasible up to a **bisection ceiling ≈ 1.971×**; above that even
  maximal withholding fails the **CM constraint only**. But each increment is expensive and
  monotone: reaching ~1.970× sacrifices **≈ −$8,300/day** net contribution and parks
  **≈ $12,700** in reserve. So a CM floor trades real contribution for a marginally higher
  portfolio ratio.
- The legacy gross **4.0× floor is slack** at today's optimum, so removing it changes the
  realistic plan by **$0**.
- **Robustness (deterministic stress seeds, dev + held-out acceptance):** a hard floor set
  near the point estimate (≤~1.94×) is violated by the realized latent response in ~100% of
  seeds — *false confidence*, not protection. A downside-adjusted guardrail could be
  defensible later but is not needed now.

*Decision.* Do **not** ship portfolio CM-ROAS floor presets. The governing instrument stays
the per-dollar **marginal CM hurdle = 1.05×** (uniform: `mᵢ × (1/mᵢ)×1.05 = 1.05×`), and the
existing efficiency-first **reserve** already provides the withhold-when-unattractive
mechanism (no new reserve-trigger abstraction). CM ROAS + net contribution remain the
objective and headline (D-041). `cm_roas_floor` stays internal, default-off, for diagnostics
only. The enforced production floor is unchanged (gross `BLENDED_ROAS_FLOOR=4.0×`), kept as a
secondary, currently-slack guardrail that does not drive the current allocation. Tests:
`tests/test_cm_floor.py` (off=no-op, slack below / infeasible above the ceiling,
growth-redundancy, sweep smoke incl. eff-first ceiling > growth ceiling). **Phase 4 closes
with a negative result; next is final UI/demo integration, not more solver features.**

## D-041 — CM ROAS + net contribution as the primary KPIs, Phase 3 of the True Classic realism update
**Stage 4 (trust & business controls).** True Classic's stated success metric is
**contribution-margin ROAS**, not gross/blended ROAS. With D-040's explicit cost stack in
place, this phase **reframes what the product headlines** — it does NOT change any
constraint, allocation, model, or fingerprint.

**Definition.** `cm_roas = (Σᵢ marginᵢ·incremental_revenueᵢ) / Σᵢ spendᵢ` on the
calibrated/incremental revenue lens (D-008). Equivalently `net_contribution =
(cm_roas − 1) × spend`. Unlike gross ROAS (which must clear break-even `1/margin ≈ 2.16×`
to pay for itself), **CM ROAS breaks even at 1.0× by construction**, so it reads directly
as "contribution dollars earned per ad dollar." The pre-D-040 numbers reconcile exactly:
current `$251,385 / $138,405 = 1.82×`, optimized `$268,585 / $138,405 = 1.94×`.

**Single source of truth.** CM ROAS and net contribution are computed once in
`optimizer._metrics` (`cm_roas`, plus `current_*`/projected on `OptResult`) — the same
allocation and margins as the optimizer objective — then threaded up unchanged through
`EngineRecommendation` → API `Kpis` → frontend, so the headline can never drift from the
objective. Tiny pure helpers `economics.cm_roas` / `economics.net_contribution` carry the
definition + identity for tests and reports.

**Surfaces reframed.** Frontend hero leads with **CM ROAS** and **net contribution $/day**
(accented `.kpi.primary` cards); calibrated gross ROAS is demoted to the *enforced
governance floor* lens and reported ROAS stays *context*. Model report (`metrics.json`
`decision` block + REPORT.md §10 + stdout) and the economics report headline CM ROAS and
net contribution. New tests: `test_economics` (break-even-at-1.0×, net identity),
`test_engine`/`test_api` (CM ROAS sits between 1.0× and gross blended ROAS; the
`net = (cm_roas − 1)·spend` identity holds end-to-end; the plan never destroys
contribution).

**Explicitly deferred to Phase 4.** The enforced floor is **still** the gross calibrated
blended ROAS (`BLENDED_ROAS_FLOOR=4.0×`). Swapping it for a CM-ROAS policy floor (with
Growth/Balanced/Conservative presets) is a separate change so any allocation delta stays
attributable to a single cause. No `config.py` constant moved → **no fingerprint change**;
`metrics.json` decision/interpretation numbers are unchanged except the added CM-ROAS/
net-contribution fields.

## D-040 — Explicit contribution economics (golden-v3 / realistic-v3), Phase 2 of the True Classic realism update
**Stage 3.5.** True Classic's stated success metric is **contribution-margin ROAS**.
The pre-D-040 margin was a coarse gross figure, `(P − C − F)(1 − r)/P`, which (a) gave
returned units free outbound fulfillment, (b) implicitly assumed 100% COGS recovery on
returns, and (c) ignored payment-processing fees and reverse-logistics handling. That
over-stated the portfolio margin (~58%).

**Decision.** Model the variable-cost stack explicitly and let the contribution margin
**emerge** (no target was forced):

```
CM = [ P(1−r) − C(1 − r·ρ) − F − f·P − r·H ] / P
```

- `F` (outbound pick/pack/ship) is now charged on **every shipped order**, including
  ones later returned (the fix for (a)).
- `C` is recovered at `ρ` (COGS recovery rate) on the returned fraction — explicit (fix
  for (b)); the prior model's implicit `ρ=1` was optimistic.
- `f·P` payment fee is charged on the **gross** sale and **retained on refund** (fix (c)).
- `H` is a per-returned-order handling cost (fix (c)).

*Pre-declared assumptions (synthetic, NOT verified True Classic ledger values).* Set
**before** observing the resulting allocation to avoid fitting the outcome:
- payment fee `f = 3%`, return handling `H = $8`, COGS recovery `ρ = 0.80` (portfolio-wide);
- base return rates per SKU `CREW-BLK 12% · POLO 14% · JOG 18% · 6PK 12%`
  (revenue-weighted ≈ **13.5%**, unit-weighted ≈ 13.3%).

*Emergent result.* Per-SKU CM `42.9% / 46.8% / 43.3% / 51.4%`; revenue-weighted **46.2%**,
spend-weighted (optimizer) **46.4%** — down from ~58% gross. Break-even ROAS rises
`1.721× → 2.157×` and the hard scale floor `1.808× → 2.264×`. Because the **safety
multiplier (1.05) is unchanged**, each campaign's marginal-revenue hurdle rises purely
because its SKU margin fell (`1.71–1.92× → 2.04–2.45×`) — the intended economic
consequence, not a policy change.

*What stayed frozen (verified).* Model/selector, portfolio policy constants
(`BLENDED_ROAS_FLOOR=4.0`, `PROSPECTING_MIN_SHARE`, `NC_CPA_TARGET`, `MOVEMENT_BOUND`),
budget scale (`PORTFOLIO_SCALE=6.0`), `HARD_FLOOR_SAFETY=1.05`, and the UI hierarchy.
The KPI headline and the gross→CM policy-floor swap are deliberately **deferred** to
Phase 3/4. Allocation barely moves (realistic ≤0.14pp shift; golden interior unchanged)
because the *relative* campaign attractiveness and the binding movement/prospecting
constraints are scale- and level-stable; only the **economics readout** (margins,
hurdles, net contribution) changes materially. Net portfolio contribution on the same
plan falls ≈34% (≈$199K → ≈$131K/day) — the point of recognizing true variable cost.

*Two fragilities Phase 2 exposed (fixed; neither is a policy/KPI change).*
1. **SLSQP feasibility ≠ solver convergence ≠ optimality (deterministic multi-start).**
   At the new objective scaling the golden optimum terminates with SLSQP **status 8**
   ("positive directional derivative for linesearch", `nit=37`, not the iteration limit)
   — a benign stop at a vertex-like constrained optimum, with **every** business
   constraint satisfied (blended ~4.08× ≥ 4.0×). The original code conflated
   `not res.success` with infeasible. **Fix (closure pass):** feasibility is defined
   SOLELY by `_business_conflicts` (the soft constraints), and `optimize()` now runs a
   deterministic multi-start (current plan, bound/interior vertices, and budget-preserving
   local perturbations), keeps every business-feasible candidate, and selects the best by
   net contribution. The binding report's `SolverStatus` exposes `business_feasible`,
   `solver_converged`, `candidate_stable`, `local_optimality_converged` and the multi-start
   trail (n_starts/n_feasible/n_near_best, best/median/worst FEASIBLE-basin contribution,
   near-best allocation spread, improvement vs current) plus a human `warning`. SLSQP
   status 0 is only a **local** convergence certificate (the ROAS-floor constraint over a
   concave response is non-convex), so nothing claims a global/"certified" optimum.
   **Profile-dependent:** on the runtime default `realistic` profile every start converges
   normally (status 0, `local_optimality_converged=True`, 5/5 feasible, +15.2% net
   contribution vs current at equal spend). Only the tight `golden` regression benchmark
   consistently lands at status 8
   (not proven impossible — just consistent for that geometry); there the feasible starts
   still agree on an identical allocation (spread 0.0) and improve net contribution, so the
   plan is **approvable with a visible "first-order optimality not solver-certified"
   warning** — never labelled a certified optimum. **Explicit stability contract:**
   near-best objective tolerance ≤ 0.05% of |best|; near-best allocations must agree to
   ≤ max($1, 0.01% of budget) per campaign; ≥2 agreeing feasible near-best starts;
   stability is measured among near-best FEASIBLE candidates only, with the worst basin
   reported separately (`worst_contribution`). Acceptance rule: business-feasible ∧
   improves-on-current ∧ (solver-converged ∨ stable multi-start). `solver_qualified` (=
   `local_optimality_converged`) is an **advisory** precondition only — it is never
   sufficient and never triggers automatic execution. Execution ALWAYS requires the M3
   human approval gate: business_feasible ∧ solver_qualified ∧ approved ∧ not-stale ∧
   no-unapproved-sensitivity-overrides. A status-8 plan (`solver_qualified=False`) stays
   benchmark-only or needs explicit reviewer acknowledgement. We deliberately do
   NOT relax the Growth-mode equality budget (Σbᵢ=B) to a tolerance band just to coax
   SLSQP to status 0: a solver status code must not redefine a business policy (the band
   would permit unintended reserve and blur the Efficiency-first mode). The warning is
   retained in API / UI / audit.
2. **Pacing flag uses the per-campaign hurdle, not the portfolio mean-margin scale
   floor.** The two were coincidentally equal pre-D-040; once SKU margins spread,
   META_PROSPECTING clears the portfolio mean-margin marginal scale floor (≈2.264×) yet
   sits below its OWN marginal hurdle (2.450×). Exposed each line's `marginal_hurdle`
   (engine `RecLine` → API `CampaignLine`) so the flag is auditable end-to-end.

*Floor terminology (named precisely — they are different objects in this temporary
Phase-2 state, do not conflate).*
- **Portfolio constraint:** `BLENDED_ROAS_FLOOR = 4.0×` — calibrated/incremental blended
  *revenue* ROAS the whole plan must clear (frozen; reported slack at ~4.08×).
- **Portfolio mean-margin marginal scale floor:** `(1/mean CM)×1.05 ≈ 2.264×` — the
  single dashed line on the marginal-ROAS chart (`marginal_scale_floor`).
- **Per-campaign marginal hurdles:** `(1/SKUᵢ CM)×1.05 ≈ 2.04–2.45×` — what each
  campaign's next-dollar return is actually judged against.
- **Common marginal CM safety multiplier:** `1.05×` (the only policy knob; frozen).

*Tests.* `tests/test_contribution.py` (structural r=0 reduction, outbound-on-returns
correction `= r·F/P`, monotonicity in every cost + recovery, waterfall reconciliation,
revenue/unit-weighted return-rate report, and a no-double-count guard proving recovery
changes ONLY the margin column — all other generated tables are byte-identical). Margin
band test widened to `0.42–0.52`. Sensitivity grid (recovery 0.50/0.80/1.00 × handling
$4/$8/$12 × base/high returns) is a reproducible report (`make econ-report`,
`reports/economics/ECONOMICS.md`), explicitly NOT promoted into the approved registry.

*Fingerprint provenance.*
- golden-v2 canonical `08643f3f…731e9` · full `de83a25f…892a59` → **golden-v3** canonical `8a302b78…c9b0` · full `637647ff…73c2`
- realistic-v2 canonical `4fa2a271…30d4a3` · full `a31fefee…49ffcf` → **realistic-v3** canonical `7ebbdf0b…0b2b` · full `399eefaa…c276`

`make generate && make test` green (248 passed). **Stopped before any KPI reframing
(Phase 3) or policy-floor swap (Phase 4), as scoped.**

## D-039 — Portfolio-scale migration (golden-v2 / realistic-v2), Phase 1 of the True Classic realism update
**Stage 3.5.** The original scenario operated at ~$24K/day, which is not credible for
True Classic's company-wide paid-media portfolio. Public reporting (a True Classic
marketer's LinkedIn post) puts the annual ad budget at **~$50–60M/yr ≈ $137–164K/day**.

**Decision.** Apply a single **homogeneous scale factor `PORTFOLIO_SCALE = 6.0`** to the
five dollar-denominated response inputs in `synth/scenario.py` only — `base_spend`,
`daily_cap`, `gamma`, `beta`, `organic_base` — via `_scale_campaign` over the new
`_UNIT_CAMPAIGNS` literals. This is a **business-scale migration, not an economics or
policy change** (the first of four planned phases; phases 2–4 — explicit variable-cost
modeling, CM-ROAS as the headline metric, and a CM-ROAS policy floor with Growth/Balanced/
Conservative presets — are deliberately **not** in this change so any future recommendation
delta is attributable to a single cause).

**Why it is economically invariant.** The Hill response `R(s)=β·sᵃ/(γᵃ+sᵃ)` satisfies
`R'(ks)=k·R(s)` when `s`, `γ` and `β` scale by `k`; the derivative (marginal ROAS) is
unchanged. Every downstream volume (revenue, orders, conversions, new customers, inventory
units) auto-scales from these inputs, so all **ratios** are preserved. Ratio/policy knobs in
`config.py` were deliberately **NOT** scaled — in particular `NC_CPA_TARGET = $45` *looks*
like a dollar field but is a per-customer ratio (spend/new_cust both ×6 → unchanged); same
for `PROSPECTING_MIN_SHARE`, `HARD_FLOOR_SAFETY`, `MOVEMENT_BOUND`, the blended-ROAS floor.
Planted defects carry no absolute-dollar magnitudes (structural/multiplicative; integer row
counts), so DQ detection is unaffected.

**Phase-1 acceptance (realistic primary profile, before → after):**

| Metric | Before ($24K) | After ($145K) | Expected | Result |
| --- | ---: | ---: | --- | --- |
| Σ base_spend / day | 21,800 | 130,800 | ×6 | ✅ exact |
| Σ daily caps | 33,800 | 202,800 | ×6 | ✅ exact |
| Engine current spend | 23,067.53 | 138,405.19 | ×6 | ✅ ×6.000 |
| Deployed interval width | 30,587.62 | 183,914.80 | ≈×6 | ✅ ×6.01 |
| Prospecting numerator | 6,940.08 | 41,638.06 | ×6 | ✅ ×6.00 |
| Blended ROAS (projected) | 4.1983 | 4.1933 | unchanged | ✅ Δ0.1% |
| Platform blended ROAS | 6.3092 | 6.3032 | unchanged | ✅ |
| NC-CPA | 5.52 | 5.52 | unchanged | ✅ identical |
| Marginal scale floor | 1.812 | 1.812 | unchanged | ✅ identical |
| Weighted margin / break-even | 0.581 / 1.721 | 0.581 / 1.721 | unchanged | ✅ identical |
| Prospecting share | 30.09% | 30.08% | unchanged | ✅ |
| Allocation % (all 7) | — | — | ≈unchanged | ✅ ≤0.003pp drift |
| Overall test WAPE | 0.1110 | 0.1110 | unchanged | ✅ |
| Deployed coverage | 0.8723 | 0.8766 | unchanged | ✅ |
| Hurdle accuracy | 0.857 | 0.857 | unchanged | ✅ identical |
| Holdout-drift set | {PMax, Retargeting} | {PMax, Retargeting} | unchanged | ✅ |
| Champion selection | — | (stable) | unchanged | ✅ XGB/drift set stable |
| Solver | success, reserve 0 | success, reserve 0 | unchanged | ✅ |

Per GPT/Cursor review we separated **exact economic invariants** (must match — they did) from
**statistical/numerical invariants** (comparable within tolerance — WAPE, coverage, conformal
offset; absolute MAE/RMSE/widths scale ≈×6). The optimizer is theoretically scale-invariant
(`mᵢ(kRᵢ)−kbᵢ = k(mᵢRᵢ−bᵢ)`); end-to-end allocation matched to **≤0.003pp** through a full
pipeline regeneration, confirming SLSQP conditioning is stable at portfolio scale (no variable
renormalization needed).

**Re-pinning (not loosened).** Updated four fingerprints to **golden-v2 / realistic-v2**;
golden-v1 / realistic-v1 hashes are recorded in `tests/test_fingerprints.py` and below.
Setting `PORTFOLIO_SCALE = 1.0` reproduces golden-v1 **byte-for-byte** today — verified in-memory
(k=1 → canonical `8873f413…`, full `aa27fe98…`), which also proves the `_UNIT_CAMPAIGNS` +
`_scale_campaign` refactor is a pure no-op at k=1. The toggle is a convenience, **not** the
authoritative restoration path: the durable golden-v1 guarantee is its recorded commit/tag plus
the pinned v1 fingerprints, since a future scenario edit could make the scale toggle alone
insufficient to reproduce every historical byte. The only non-fingerprint test touched was
`test_movement_bounds_respected`: its `1e-6` epsilon was an absolute tolerance implicitly tuned
to small dollars; the ±20% bound is enforced on the optimizer's *continuous* dollars and a 2-dp
rounding can sit ≤½¢ past it at scale, so the tolerance is now **0.01 (one cent)** — still strict
to the cent, not widened to pass. No exact-dollar test assertions existed to multiply (the suite
already used ratio invariants). `make generate && make test && make model-report && make marts`
all green; marts re-seeded at portfolio scale (identity gate passes).

*Fingerprint provenance.*
- golden-v1 canonical `8873f413…890a4` · full `aa27fe98…6e7e3` → **golden-v2** canonical `08643f3f…731e9` · full `de83a25f…892a59`
- realistic-v1 canonical `66b5dd59…a6cc5` · full `a7644691…1fe10` → **realistic-v2** canonical `4fa2a271…30d4a3` · full `a31fefee…49ffcf`

*Phase-1 hardening (post-review).* Added permanent contract tests so the best
evidence does not live only in this log: `test_portfolio_scale_is_economically_invariant`
(parametrized k=1/6/13 — asserts revenue scales by k while avg/marginal ROAS, utilization
and spend/γ stay equal, exercising the production `_scale_campaign` helper) and
`test_active_portfolio_scale_matches_pinned_fixture` (pins `PORTFOLIO_SCALE = 6.0` and the
$130.8K/$202.8K daily sums, so the scale can't drift without a deliberate fingerprint bump).
Verified the 1-cent movement-bound tolerance is confined to that one *post-rounding monetary*
check — dimensionless constraints (marginal-ROAS ordering, ROAS/prospecting feasibility)
retain strict `1e-6`/unit tolerances. Stale-value audit: active surfaces (README, Next.js UI,
`scripts/`, tests) carry no hard-coded small-scale dollars (they render live engine output);
pre-D-039 decision-log narratives (e.g. the Stage-4 "≈$714 reserve" demo beat) are left as
historical, since rewriting them to portfolio scale would be anachronistic.

## D-009 — Fingerprint regression test is environment-pinned
**Stage 0.** `test_fingerprints.py` asserts a committed combined fingerprint.
**Decision:** treat it as a regression guard tied to the pinned dependency set,
not a portability guarantee. Dependency bumps that change float rendering require
regenerating the fingerprint and a new entry here. **Impact:** one test.

---

## Adherence to operating constraints (Stage 0)

- ✅ Vertical slice that stays runnable; Stage 0 only — no Stage 1–6 code.
- ✅ No Amazon / Microsoft in the committed implementation.
- ✅ No Streamlit; stack remains Next.js + FastAPI (frontend/backend scaffolded).
- ✅ No Prophet, no full MMM, no autonomous runtime orchestration, no real OAuth,
  no live media writes.
- ✅ No XGBoost / Hill fitting / SLSQP / LLM implemented in Stage 0.
- ✅ All numerical generation deterministic (pinned seed, explicit child streams).
- ✅ Tests assert business invariants & tolerances, not one exact allocation.
- ✅ Clear separation: real schema/contract code · synthetic data · stubbed execution.
- ✅ No causal-identification claim from synthetic data (stated in README & Q&A lines).

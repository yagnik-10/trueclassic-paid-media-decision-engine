#  True Classic Paid Media Decision Engine

An auditable, vendor-neutral cross-platform paid-media **decision & governance
layer**. It turns fragmented Meta + Google media data and Shopify commerce truth
into **risk-aware, marginal-economics budget recommendations**, while keeping
measurement inputs, business constraints, human approval, and execution adapters
independently replaceable.

> **Thesis:** optimize risk-adjusted *net contribution at the margin* subject to
> ROAS / NC-CPA / prospecting / inventory constraints — **marginal ROAS, not
> average ROAS**. A 6× historical channel may be saturated; a 4× channel may have
> profitable room. Allocation depends on the next dollar's expected return.

The canonical architecture and build plan live in
[docs/FINAL_PLAN.md](docs/FINAL_PLAN.md). It is the source of truth; proposed
deviations are recorded in [docs/DECISIONS.md](docs/DECISIONS.md).

> **Platform scope.** The runnable vertical slice covers **Meta and Google** (the
> minimum needed to prove cross-platform reallocation). Amazon is **not**
> implemented; it follows the same connector + canonical-schema pattern and is the
> next platform extension — no new decision logic, only another ingestion adapter.

---

## What is real vs. stubbed

| Real (this prototype) | Synthetic / Stubbed |
|---|---|
| Canonical schema contracts (Pandera + Pydantic) | The **data** is deterministic synthetic (clearly labelled) |
| Deterministic API-envelope-shaped data generator | Incrementality coefficients are **synthetic**, not measured |
| Planted data-quality defects + explicit quarantine **states** in the artifacts | Execution payloads are **stubbed** (no real OAuth, no live writes) |
| Golden-scenario business invariants & tolerances | — |
| Approve/reject decision flow (idempotent; rejected can't execute) over a **durable, append-only, hash-chained** audit ledger (SQLite) | Execution payloads are **stubbed**; the ledger persists decisions but does not call platform APIs |
| (later stages) ingestion adapters & quarantine **service**, XGBoost BAU forecast, adstock–Hill response, SLSQP optimizer, **durable** approval/audit, bounded LLM | — |

Stage 0 represents quarantine **states** (e.g. `data_quality_issue` rows and
`sku_alias.match_status = quarantined`) — it does **not** ship a reusable
ingestion/quarantine **service** or raw-record→canonical **normalization**; those
are Stage 2.

We do **not** claim causal identification from synthetic or observational data.
The synthetic set verifies the system can *recover a known response process*;
production calibration still requires lift experiments.

---

## Build status — staged vertical slice

The system is built as a vertical slice that stays runnable. **Stages 0–3 are
complete.**

- **Stage 0 ✅ — Golden scenario + synthetic-truth contract**:
  canonical schemas, deterministic generator, planted defects, locked business
  invariants with tolerances.
- **Stage 1 ✅ — Thin end-to-end shell**: web UI → FastAPI endpoint →
  static canonical dataset → one **fixed** recommendation → approve/reject with a
  **stubbed** audit (idempotent approval; a rejected plan cannot execute). The
  seam works before any real modeling. (The original Next.js shell has since been
  retired in favor of the Vite + React SPA in `frontend/` — see
  `docs/DECISIONS.md` D-043.)
- **Stage 2 ✅ — Real ingestion**: Meta `data/paging` + Google nested `results` +
  Shopify adapters flatten the raw API-shaped JSON into the canonical model, with
  two-level (envelope + record) validation & **quarantine**, deterministic **SKU
  reconciliation** (auto / needs-approval / quarantine with a human approval), and
  **data-quality defects detected from the feeds** (dedup, missing dates, micros
  normalization, null new-customer, reconciliation, coverage gaps, label maturity,
  and an **attribution-window conflict** — the observed per-campaign attribution
  model is compared against the canonical comparison policy and surfaced, never
  silently normalized). Surfaced in an **Ingestion & reconciliation** UI view.
- **Stage 3 ✅ — Real engine**: the fixed recommendation is replaced by a
  deterministic engine that **recovers the scenario from observable data** —
  XGBoost **quantile** BAU forecast (P10/P50/P90, monotonic; promoted over the
  **champion baseline** — the better of trailing-14d / same-weekday — only when **one
  shared, frozen selector** (used by both the live engine and the eval report, so they
  can never disagree, and which returns the *exact* deployed model so the comparison
  baseline is the deployed baseline) finds it beats that champion by a *material* margin
  across pre-test folds) + an **orthogonalized (double-ML)**
  residualized spend-response that recovers the marginal-ROAS ordering + a **SciPy
  SLSQP** optimizer maximizing calibrated net contribution under the **calibrated**
  ROAS floor (per-campaign marginal hurdles, prospecting/NC-CPA/movement/inventory
  constraints), with an explicit infeasibility conflict report. The two models are
  composed per the plan: the optimizer's per-campaign revenue **level** is anchored on
  the **selected BAU forecast** (the forward-7-day P50 ÷ horizon, an average daily
  level), and the response curve adds only the **spend-change delta** (`R(b) −
  R(b_current)`, zero at current spend) — so Model A feeds the allocation and the two
  models cannot double-count. The marginal magnitudes are recovered via adstocked
  double-ML so the optimizer can lift calibrated blended ROAS across 4.0 (3.76 → 4.06).
  Marginal ROAS, reported-vs-calibrated ROAS, and the
  7-day forecast are shown in the UI. The marketer can **adjust constraints live**
  (validated ROAS floor / NC-CPA / prospecting / movement, Expected vs Conservative)
  and the plan re-solves in ~10 ms (the expensive forecast/response state is cached).
  Each plan is an **immutable snapshot** with a deterministic `scenario_id`;
  **approval binds to that snapshot by id** (never re-solves), over-tightening shows
  the exact-shortfall conflict report and disables Approve. A structured **"why this
  plan"** report names which business constraints bind vs. slack and the hard bound
  pinning each campaign (see [DECISIONS.md](docs/DECISIONS.md) D-025).
  - **Honest caveats:** NC-CPA is an *approximate monitored guardrail*, not a binding
    optimizer constraint (it never binds; prospecting share is the real top-of-funnel
    protection); and the calibration registry copies the scenario's true incrementality,
    so calibration *error* is still synthetic (the S4.3 sensitivity lever lets you stress
    it, but it is not measured lift). The 80% prediction interval is now **conformal
    (CQR) calibrated** (held-out coverage ≈ 83% vs the 80% target, up from ≈ 43% raw) but
    remains **display-only** — the decision basis is still the marginal ordering + ROAS
    floor, not the band.
- **Stage 4 (in progress) — Trust & business controls:** ✅ 4.1 reserve / efficiency-first
  modes + pacing & budget-utilization view; ✅ 4.2 conformal interval calibration; ✅ 4.3
  platform-vs-calibrated ROAS calibration registry + live coefficient sensitivity
  (non-approvable what-ifs). Provenance hardening (D-030): immutable config snapshot, an
  approved-calibration-registry identity in the scenario id / stale guard / audit,
  idempotent terminal decisions, and a solver-status + reserve binding report. ✅ 4.4
  durable, append-only, **hash-chained** audit ledger (SQLite) — decisions survive
  restarts, are tamper-evident (`GET /api/audit/verify`), and retain full
  data/config/calibration/binding provenance. ✅ 4.5 **Looker-ready SQL marts** —
  four single-grain views over the ledger (decision, allocation line, binding
  constraint, audit chain), served at `/api/marts/{name}` and exportable to DDL +
  CSV via `make marts`. Stage 4 complete.
- Stage 5 — Bounded LLM (SKU ranking + grounded narration).
- Stage 6 — Harden (seeded demo, pretrained artifacts, deployed backup).

---

## Quickstart

```bash
make setup        # python3.13 venv + EXACT locked deps (engine + API)
make generate     # write the GOLDEN dataset → data/canonical/*.csv|parquet|duckdb|manifest.json + data/raw/*.json
make generate-realistic  # write the REALISTIC profile → data/realistic/ (volatility + exogenous spend variation, D-034)
make test         # run the test suite (engine + API)
make fingerprint  # print + verify the full-artifact fingerprint (primary)
make verify-clean-install   # build a throwaway venv from the lock and run the suite
```

### Run the app

Two processes — the FastAPI backend and the Vite/React web UI (`frontend/`):

```bash
make api          # FastAPI backend  → http://127.0.0.1:8000  (docs at /docs)
make web-setup    # one-time: install web UI (Vite + React) deps
make web          # Vite dev server  → http://localhost:3000
```

Open http://localhost:3000: review the **optimizer** budget-reallocation
recommendation (current vs recommended per campaign, marginal CM ROAS, reason/risk
codes, calibrated-vs-reported ROAS, forecast bands, and the analysis charts) and
**Approve** or **Reject** — an **infeasible** plan cannot be approved. Approve
emits **stubbed** Meta/Google execution payloads (no live writes); the
inventory-constrained campaign is flagged and not scaled. The backend is
single-service (FastAPI) by design — the web client is a read-and-govern layer
over its endpoints.

`make setup` installs the **exact tested versions** from `requirements-lock.txt`
(now including the FastAPI/uvicorn/httpx API stack and the scipy/scikit-learn/
xgboost engine stack; use `make setup-dev` for the looser pyproject ranges).
**XGBoost needs the OpenMP system runtime** (not pip-installable): on macOS run
`brew install libomp`; on Debian/Ubuntu `apt-get install libgomp1`.
`make generate` prints row counts, planted-defect counts, and writes
`manifest.json` (seed, versions, row counts, logical fingerprints). The **main
reproducibility hash is the full-artifact fingerprint** — it covers every
canonical table plus the Meta/Google/Shopify envelopes, versions, seed, and
dependency versions (a separate canonical-tables-only fingerprint is also
recorded). Generation is fully offline and deterministic (`MASTER_SEED`).

### Two dataset profiles (D-034 / D-035)
Two deterministic profiles share the **same latent truth** but differ in the
observable driving process, selected via `TC_DATASET_PROFILE`:
- **`realistic` — the PRIMARY data (default).** Structured seasonality/promos,
  heteroscedastic noise + shocks, and **exogenous staggered budget experiments**
  on a subset of campaigns (the rest stay observational). This is what the engine,
  API, and `reports/model_performance` use. Lives in `data/realistic/`.
- **`golden` — the regression BENCHMARK.** The tight, smooth known-truth scenario;
  the test suite pins itself to it (`tests/conftest.py`) so it stays the
  deterministic anchor. Lives at `data/{raw,canonical}`.

`make generate` writes both; `make generate-realistic` / `make generate-golden`
write one. `make fingerprint` verifies both pinned fingerprints.

### Real vs. synthetic vs. latent — three layers
- **Observable synthetic data** — the API-envelope JSON in `data/raw/` (what an
  adapter would ingest).
- **Canonical tables** — the 13 unified, model-ready tables in `data/canonical/`.
- **Internal latent generator truth** — the known response process (marginal
  ROAS, incrementality, noise). It is **never** written to `data/canonical` or
  `data/raw`; it lives in memory for tests and is persisted only under
  `data/internal/latent/` behind an explicit `--write-latent-truth` flag. This
  prevents target leakage into any model-input path.

---

## Stage 0 — the golden scenario

Seven campaigns across **Meta + Google** and four real True Classic products
(synthetic economics), with deliberately-designed tensions encoded as known
adstock–Hill response curves:

- **Meta Dynamic Retargeting** — high *platform* ROAS, saturated (low marginal),
  planted over-attribution → should **decrease**.
- **Google Nonbrand Search** — genuine room to scale (high in-support marginal) →
  should **increase**.
- **Meta Broad Prospecting** — caps out early, productive at the margin → must
  **stay funded** (NC-CPA / prospecting-floor binding).
- **Google Brand Search** — high average ROAS but saturated and under-utilized.
- **Google PMax / Shopping** — attractive economics, but the promoted SKU
  (Black Active Joggers) is **inventory-constrained**, blocking part of the scale-up.

Plus 11 planted data-quality defects (duplicate Meta row, missing Google
extraction date, `cost_micros` normalization, mismatched SKU aliases, a SKU
candidate needing approval, an unknown SKU to quarantine, null new-customer
values, immature conversion labels, an attribution-window mismatch, platform
revenue exceeding Shopify DTC, and inconsistent date coverage).

Tests assert **business invariants and tolerance ranges**, not one exact
optimizer allocation — leaving the Stage-3 optimizer room to solve while the
scenario's tensions stay guaranteed.

### Stage 0 scope (what ships, what was removed as premature, what's deferred)

**Stage 0 ships:** repository/governance scaffolding; the 13 canonical schemas;
deterministic Meta/Google/Shopify-shaped synthetic outputs; SKU, inventory, and
calibration reference data; the golden scenario with 11 planted defects and
explicit quality/quarantine **states**; latent-truth isolation; typed persistence;
dependency locking; the full-artifact manifest + logical fingerprints; and tests
for determinism, schemas, defects, sanity, and observable scenario invariants
(including a broad property that the scenario *supports* a future feasible
optimization — no allocation is computed).

**Removed as premature during the Stage 0 scope reset** (deferred with their
design notes in [docs/DECISIONS.md](docs/DECISIONS.md) D-020):
- raw-record → canonical **normalization** and a reusable validation/quarantine
  **service** → **Stage 2**;
- a constrained **allocation search / feasibility witness** and
  **reserve-feasibility** policy → **Stage 3/4**.

**Remains for Stages 1–6:** thin end-to-end shell (1) · real ingestion adapters,
validation service, SKU resolution (2) · forecasting + residualized response +
SLSQP optimizer (3) · trust controls, calibration sensitivity, approval/audit,
inventory, reserve modes (4) · bounded LLM (5) · hardening (6).

---

## Layout

```
backend/decision_engine/   decision-engine package
  config.py                pinned seed, paths, policy constants
  schemas/                 Pandera (canonical) + Pydantic (API envelopes)
  synth/                   scenario truth, generator, defects, envelope writers, fingerprint
backend/api/               FastAPI shell (recommendation, ingestion, audit, marts)
frontend/              Vite + React web UI (5-tab decision & governance client)
scripts/                   CLI entrypoints (data generation, fingerprint verify)
data/                      generated artifacts (gitignored)
tests/                     engine + API test suite
docs/                      FINAL_PLAN, DECISIONS, AI_WORKFLOW
```

## Tech stack

Vite + React 19 + TypeScript (web UI, `frontend/`) · FastAPI + Python (backend) ·
DuckDB + pandas (analytics) · Pandera + Pydantic (validation) ·
XGBoost + SciPy SLSQP (Stage 3 modeling) · bounded LLM narrator (Stage 5 —
OpenAI or Anthropic via env keys; served by `gpt-4o-mini` in this demo, with a
deterministic template fallback). Build-time AI: Claude Code / Cursor.

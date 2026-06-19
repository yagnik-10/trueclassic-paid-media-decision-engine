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

---

## What is real vs. stubbed

| Real (this prototype) | Synthetic / Stubbed |
|---|---|
| Canonical schema contracts (Pandera + Pydantic) | The **data** is deterministic synthetic (clearly labelled) |
| Deterministic API-envelope-shaped data generator | Incrementality coefficients are **synthetic**, not measured |
| Planted data-quality defects + explicit quarantine **states** in the artifacts | Execution payloads are **stubbed** (no real OAuth, no live writes) |
| Golden-scenario business invariants & tolerances | — |
| Stage 1 approve/reject decision flow (idempotent; rejected can't execute) | Execution payloads are **stubbed**; the audit is **in-memory** (a durable, append-only audit store is Stage 4) |
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

The system is built as a vertical slice that stays runnable. **Stages 0–2 are
complete.**

- **Stage 0 ✅ — Golden scenario + synthetic-truth contract**:
  canonical schemas, deterministic generator, planted defects, locked business
  invariants with tolerances.
- **Stage 1 ✅ — Thin end-to-end shell**: Next.js page → FastAPI endpoint →
  static canonical dataset → one **fixed** recommendation → approve/reject with a
  **stubbed** audit (idempotent approval; a rejected plan cannot execute). The
  seam works before any real modeling.
- **Stage 2 ✅ — Real ingestion**: Meta `data/paging` + Google nested `results` +
  Shopify adapters flatten the raw API-shaped JSON into the canonical model, with
  two-level (envelope + record) validation & **quarantine**, deterministic **SKU
  reconciliation** (auto / needs-approval / quarantine with a human approval), and
  **data-quality defects detected from the feeds** (dedup, missing dates, micros
  normalization, null new-customer, reconciliation, coverage gaps, label maturity).
  Surfaced in an **Ingestion & reconciliation** UI view.
- Stage 3 — Real engine (baselines → XGBoost BAU → cross-fitted residualized adstock–Hill → SLSQP).
- Stage 4 — Trust & business controls (quantiles, calibration sensitivity, approval/audit, inventory, reserve modes, Looker-ready marts).
- Stage 5 — Bounded LLM (SKU ranking + grounded narration).
- Stage 6 — Harden (seeded demo, pretrained artifacts, deployed backup).

---

## Quickstart

```bash
make setup        # python3.13 venv + EXACT locked deps (engine + API)
make generate     # write data/canonical/*.csv|parquet|duckdb|manifest.json + data/raw/*.json
make test         # run the test suite (engine + API)
make fingerprint  # print + verify the full-artifact fingerprint (primary)
make verify-clean-install   # build a throwaway venv from the lock and run the suite
```

### Run the app (Stage 1 thin shell)

Two processes — the FastAPI backend and the Next.js frontend:

```bash
make api          # FastAPI backend  → http://127.0.0.1:8000  (docs at /docs)
make web-setup    # one-time: install frontend (Next.js) deps
make web          # Next.js frontend → http://localhost:3000
```

Open http://localhost:3000: review the fixed budget-reallocation recommendation
(current vs recommended per campaign, reason/risk codes, blended-ROAS KPIs) and
**Approve** or **Reject**. Approve emits **stubbed** Meta/Google execution
payloads (no live writes); the inventory-constrained campaign is flagged and not
executed. The backend is single-service (FastAPI) by design — Next.js already
covers the Node/TS side.

`make setup` installs the **exact tested versions** from `requirements-lock.txt`
(now including the FastAPI/uvicorn/httpx API stack; use `make setup-dev` for the
looser pyproject ranges during development).
`make generate` prints row counts, planted-defect counts, and writes
`manifest.json` (seed, versions, row counts, logical fingerprints). The **main
reproducibility hash is the full-artifact fingerprint** — it covers every
canonical table plus the Meta/Google/Shopify envelopes, versions, seed, and
dependency versions (a separate canonical-tables-only fingerprint is also
recorded). Generation is fully offline and deterministic (`MASTER_SEED`).

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
backend/api/               Stage 1 FastAPI shell (recommendation + approve/reject audit)
frontend/                  Stage 1 Next.js page (recommendation review & approval)
scripts/                   CLI entrypoints (data generation, fingerprint verify)
data/                      generated artifacts (gitignored)
tests/                     engine + API test suite
docs/                      FINAL_PLAN, DECISIONS, AI_WORKFLOW
```

## Tech stack

Next.js + TypeScript (Stage 1 frontend) · FastAPI + Python (backend) ·
DuckDB + pandas (analytics) · Pandera + Pydantic (validation) ·
XGBoost + SciPy SLSQP (Stage 3 modeling) · Claude (Stage 5 bounded LLM,
`claude-sonnet-4-6`, with deterministic fallbacks).

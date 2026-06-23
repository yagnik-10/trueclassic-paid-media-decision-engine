# True Classic — Paid Media Decision Engine

A cross-platform paid-media **budget decision & governance layer** for **Meta + Google**.
It ingests fragmented ad data, forecasts 7-day performance, and recommends budget
reallocations on **marginal economics** — then puts a marketer in the loop to approve
before any (stubbed) execution.

> **Core idea — marginal ROAS, not average.** A 6× channel can be saturated (the next
> dollar is wasted); a 4× channel can have room to scale. The optimizer maximizes
> risk-adjusted **net contribution at the margin** subject to ROAS / NC-CPA / prospecting /
> inventory / movement guardrails — and surfaces *why* each campaign moves.

**Stack:** Vite + React 19 + TypeScript (web) · FastAPI + Python (backend) · XGBoost
**quantile** forecast + **conformal (CQR)** intervals · **double-ML / adstock-Hill**
spend-response · SciPy **SLSQP** optimizer · DuckDB + pandas · Pandera + Pydantic ·
**SQLite hash-chained** audit ledger · **bounded LLM narrator** (OpenAI `gpt-4o-mini` or
Anthropic, with a deterministic fallback). Built with **Claude Code + Cursor**.

---

## Run it

```bash
brew install libomp                 # macOS: XGBoost's OpenMP runtime (Debian/Ubuntu: apt-get install libgomp1)
make setup                          # python3.13 venv + EXACT locked deps
make generate                       # write both synthetic datasets, deterministically (folders auto-created)
make api                            # FastAPI backend → http://127.0.0.1:8000  (OpenAPI at /docs)
make web-setup && make web          # Vite + React UI → http://localhost:3000
```

Open the UI → review the recommendation (current vs recommended per campaign, marginal
CM-ROAS, forecast bands, the LLM narration) → **Approve / Reject**. An **infeasible** plan
cannot be approved; approval writes to the hash-chained audit ledger and emits **stubbed**
Meta/Google budget calls (no live writes). To narrate with a live LLM, set `OPENAI_API_KEY`
or `ANTHROPIC_API_KEY` (see `.env.example`) — otherwise it falls back to a deterministic
template. `make verify-clean-install` builds a throwaway venv and runs the suite from scratch.

### Windows

The commands above assume a Unix shell (`make` plus a macOS/Linux venv layout). On Windows,
use **WSL2 (recommended)** or run the steps natively without `make`.

**WSL2 (Ubuntu) — the smooth path.** Inside the Ubuntu shell, install Python 3.13 and
`sudo apt-get install libgomp1` (XGBoost's OpenMP runtime), then use the exact same
`make setup / generate / api / web` targets shown above.

**Native Windows (PowerShell), no `make`** — run each step directly:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-lock.txt
pip install -e . --no-deps
python scripts/generate_synthetic_data.py --profile golden      # benchmark (tests pin to this)
python scripts/generate_synthetic_data.py --profile realistic   # primary data (engine/API/reports)
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000       # backend (one terminal)
cd frontend; npm install; npm run dev                           # UI → http://localhost:3000 (another terminal)
```

- XGBoost's Windows wheel **bundles OpenMP** — no `libomp` needed (it uses the MSVC runtime).
- All pinned deps ship Windows `cp313` wheels, so `pip install` works on Python 3.13.
- Determinism holds with the fixed seeds + `n_jobs=1`; in rare cases cross-OS float rounding
  could shift a pinned fingerprint, so `make test` is best run on WSL2 / macOS / Linux.

---

## What's REAL (working end-to-end)

- **Ingestion & cross-platform unification** — Meta (`data/paging`) + Google (nested
  `results`) + Shopify adapters flatten raw API-shaped JSON into 13 canonical tables, with
  envelope+record validation, **quarantine**, deterministic **SKU reconciliation**
  (auto / needs-approval / quarantine + a human approval), and data-quality detection
  (dedup, missing dates, `cost_micros` normalization, an **attribution-window conflict**,
  label maturity, coverage gaps…).
- **Forecasting** — XGBoost **quantile** P10/P50/P90 (monotone in spend), validated on
  gap-aware walk-forward folds and **promoted over naive baselines only when it *materially*
  beats them** (one shared selector used by both the engine and the eval report). 80%
  intervals are **conformal-calibrated** (held-out coverage ≈ 81% vs ≈ 40% raw, target 80%).
- **Response model** — orthogonalized **double-ML / FWL on adstocked spend** recovers the
  **marginal-ROAS ordering** from confounded observational data (validated against the
  known synthetic truth — see the honest limit below).
- **Optimizer** — SciPy **SLSQP** maximizes calibrated **net contribution / CM-ROAS** under
  the calibrated ROAS floor, NC-CPA, prospecting floor, ±movement, daily caps, inventory
  holds, and per-campaign marginal hurdles; infeasible inputs return an **exact-shortfall
  conflict report**. Re-solves in ~10 ms as you adjust constraints live.
- **Governance** — **immutable scenario snapshots** (deterministic `scenario_id`),
  approve-by-snapshot (never re-solves), **supersession + stale guards**, and a **durable,
  append-only, hash-chained SQLite audit ledger** that's tamper-evident via
  `GET /api/audit/verify`, plus **Looker-ready SQL marts** over the ledger.
- **Trust controls** — a synthetic **incrementality calibration registry** with live
  coefficient **sensitivity** (non-approvable what-ifs), **reserve / efficiency-first**
  budget modes, inventory holds, and platform-reported-vs-calibrated ROAS.
- **Bounded LLM narrator** — explains the *validated* plan in 2-3 executive sentences. It
  **never computes, allocates, ranks, or decides** (every number renders from app state),
  with grounding guardrails (rejects fabricated campaigns / overclaims) and a
  **deterministic template fallback** so the demo can't break.
- **Web UI** — a Vite/React client over the API: decision overview, data unification,
  forecast & response, budget planner (live constraint editing), and audit & business
  controls.

## What's MOCKED / SYNTHETIC / STUBBED (stated plainly)

- **Data is deterministic synthetic** — Meta/Google/Shopify-shaped, seeded (`MASTER_SEED`),
  reproducible byte-for-byte and fingerprint-pinned. Clearly labelled; not real account data.
- **Incrementality is synthetic** — the calibration registry stands in for geo/conversion-lift /
  MMM; calibration *error* isn't measured (the sensitivity view stresses it, but it's not real lift).
- **Execution is stubbed** — no real OAuth, no live budget writes. Approval emits the exact
  set-budget payloads that *would* be sent (their hashes match the audit ledger), but nothing
  leaves the box.
- **No causal claim** — the synthetic set proves the system can *recover a known response
  process*; production calibration still needs lift experiments.
- **Honest limit:** on the realistic (noisy) profile the per-campaign allocation **direction is
  recovered but not yet decision-grade** under marginal uncertainty (the model report reports
  `safe_for_decision_demo: False`). The strength is **forecast + calibrated intervals +
  governance + human approval** — the allocation is directional-with-guardrails, not gospel.
  (The smooth `golden` profile recovers cleanly and is the regression anchor.)

## What I'd build next (with 2 more weeks)

1. **Real platform writes** — Meta Marketing + Google Ads OAuth behind the *same* execution
   adapter (the stubbed payload contract already exists); shadow-mode first, then a limited,
   human-approved copilot.
2. **Real incrementality** — wire geo / conversion-lift experiments to replace the synthetic
   calibration coefficients, with measured uncertainty feeding the optimizer.
3. **Make the allocation decision-grade** — more campaigns + identifying spend variation (or
   experiment-derived marginals) so per-campaign direction is robust under noise, not just the
   smooth case.
4. **More platforms** — Amazon + Microsoft adapters (same connector + canonical-schema
   pattern — *no new decision logic*, only another ingestion adapter).
5. **Drift & monitoring** — model/calibration drift alerts; Triple Whale / Looker integration
   off the existing marts.

---

## Reproducibility & layout

- **Deterministic** — fixed `MASTER_SEED`, single-threaded models; two pinned full-artifact
  **fingerprints** (`make fingerprint`). Two profiles share the **same latent truth**:
  **`realistic`** (default — seasonality, heteroscedastic noise, exogenous budget experiments)
  and **`golden`** (smooth known-truth benchmark; the test anchor), selected via
  `TC_DATASET_PROFILE`. `make generate` writes both; folders are created automatically.
- **Latent truth never leaks** — the known response process (marginal ROAS, incrementality,
  noise) is **never** written to `data/canonical` or `data/raw`; it stays in memory for tests
  and is persisted only under `data/internal/latent/` behind an explicit flag (prevents target
  leakage into any model-input path).
- **Generated data is gitignored** and recreated by `make generate`.

```
backend/decision_engine/  engine: canonical schemas, synthetic generator, forecast,
                          double-ML response, SLSQP optimizer, calibration, conformal intervals
backend/api/              FastAPI: recommendation, ingestion, audit ledger, marts, LLM narration
frontend/                 Vite + React 19 web UI
scripts/  tests/  data/   CLI entrypoints · test suite · generated artifacts (gitignored)
```

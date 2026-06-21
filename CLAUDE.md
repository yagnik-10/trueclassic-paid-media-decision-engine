# CLAUDE.md — guidance for AI assistants in this repo

This is the **True Classic Paid Media Decision Engine**. Read this
before changing code.

## Canonical sources
- `docs/FINAL_PLAN.md` is the **canonical architecture & build plan**. Do not
  replace its architecture with a simpler or broader alternative without first
  documenting the change, rationale, risks, and impact in `docs/DECISIONS.md`.
- `TrueClassic_AIExercise_PaidMedia_v2.docx` is the original brief (context).

## Hard rules (do not violate)
- Build as a **vertical slice that stays runnable**. One stage at a time; do not
  build the whole system in one pass.
- **Meta + Google only** in the committed implementation. No Amazon / Microsoft.
- Stack is **Vite + React (TypeScript) + FastAPI**. No Streamlit substitute. The
 web UI lives in `frontend/`; the original Stage-1 Next.js shell was retired
 (see `docs/DECISIONS.md` D-043).
- No Prophet, no full MMM, no autonomous runtime orchestration, no real OAuth,
  no live media writes.
- **All numerical decisions are deterministic.** The LLM may only rank allowed
  SKU candidates or narrate validated results — never compute, allocate, or
  execute. Every LLM feature needs a deterministic template fallback.
- Use **pinned seeds and deterministic synthetic generation**. Never touch the
  global numpy RNG; derive child streams from `config.MASTER_SEED`.
- Test **business invariants and tolerances**, not one exact optimizer allocation.
- Keep clear separation between **real implementation**, **synthetic data**, and
  **stubbed execution**. Never claim causal identification from synthetic or
  observational data.
- **Latent generator truth** (`scenario_truth`: marginal ROAS, incrementality,
  noise) must never reach `data/canonical` or `data/raw` — it is a target-leakage
  risk. It stays in memory / `data/internal/latent` (opt-in flag only).
- **The scale-floor threshold is derived, not a magic number** — see
  `backend/decision_engine/economics.py` (hard floor = break-even = 1/margin × safety).
  Only the safety multiplier in `config.py` is a policy knob. (Efficiency-first
  hurdles, reserve, and any optimizer/ingestion policy are LATER stages — not
  Stage 0.)

## Stage boundary (do not cross in Stage 0)
- Raw-record → canonical **normalization / ingestion adapters** are **Stage 2**.
- The **optimizer / allocation search / reserve feasibility** are **Stage 3/4**.
  Stage 0 only proves the scenario *supports* a future feasible optimization;
  it never computes one.

## Where things live
- `backend/decision_engine/config.py` — pinned seed, paths, policy constants. Changing
  a constant is a scenario change; update the fingerprint test + DECISIONS.md.
- `backend/decision_engine/economics.py` — the economically-derived scale floor
  (break-even × safety) + latent-truth helpers used to characterize the scenario.
  Imports `scenario` (kept config-independent to avoid an import cycle).
- `backend/decision_engine/schemas/` — `canonical.py` (Pandera, 13 tables) and
  `envelopes.py` (Pydantic API-envelope shapes for the synthetic outputs).
- `backend/decision_engine/synth/` — `scenario.py` (the *known truth*, pure response
  math), `generator.py`, `defects.py` (11 planted defects + expected counts),
  `envelope_writers.py`, `fingerprint.py`, `manifest.py`, `persistence.py`.
- `requirements-lock.txt` — exact tested deps; `make setup` installs from it.
  Bump → regenerate the fingerprint and record in `docs/DECISIONS.md`.
- `tests/` — determinism, envelopes, schemas, planted defects, value sanity,
  business invariants, fingerprints.

## Stage status
Stages 0–3 are complete: Stage 0 (schemas, generator, defects, invariants),
Stage 1 (FastAPI thin shell + web UI + stubbed approve/reject audit),
Stage 2 (real ingestion: adapters, validation/quarantine, SKU resolution, DQ
detection), Stage 3 (real engine in `backend/decision_engine/engine/` — XGBoost
quantile BAU forecast + baselines, orthogonalized/double-ML residualized response,
SciPy SLSQP optimizer with feasibility handling; the recommendation is now a real
optimizer result, `is_fixed_placeholder=False`). Stage 4 (trust & business
controls: quantile/uncertainty charts, calibration sensitivity, durable
approval/audit, reserve modes, Looker-ready marts) is also in place. **Stage 5
(bounded LLM) has begun:** the recommendation narrator is live (narration only,
deterministic fallback — `backend/api/llm.py`, `GET …/narration`, D-047); SKU
ranking and NL constraint parsing are still pending. The LLM never computes,
allocates, or executes — numbers always render from app state.
Engine numbers are deterministic (fixed seeds, `n_jobs=1`); xgboost needs the
OpenMP runtime (`brew install libomp`).

## Dataset profiles (D-034 / D-035)
Two deterministic profiles share the same latent truth, selected via
`TC_DATASET_PROFILE`. **`realistic` is the PRIMARY/default data** (volatility +
exogenous spend experiments; `data/realistic/`) — what the engine/API/report use.
**`golden`** is the smooth known-truth **regression benchmark** (`data/{raw,canonical}`);
the test suite hard-pins to it in `tests/conftest.py`, so golden stays the
deterministic anchor. Both fingerprints are pinned; `make generate` writes both.

## Workflow
- `make setup && make generate && make test` must stay green.
- If you change generated values, regenerate and update the pinned fingerprints in
  `tests/test_fingerprints.py` (golden AND realistic), recording why in
  `docs/DECISIONS.md`. Golden's fingerprint must not move unless intentionally.
- Match the surrounding code's style and comment density.
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
- Stack is **Next.js + FastAPI**. No Streamlit substitute.
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
Stages 0–1 are complete: Stage 0 (schemas, generator, defects, invariants,
governance docs) and Stage 1 (FastAPI thin shell in `backend/api/` + Next.js page
in `frontend/`, one fixed recommendation + stubbed approve/reject audit). Next is
Stage 2 (real ingestion adapters). Do **not** implement XGBoost, Hill fitting,
SLSQP, or the LLM yet — those are Stage 3/5. The Stage 1 recommendation is a
labelled FIXED placeholder, not an optimizer result.

## Workflow
- `make setup && make generate && make test` must stay green.
- If you change generated values, regenerate and update
  `tests/test_fingerprints.py::EXPECTED_COMBINED_FINGERPRINT`, recording why in
  `docs/DECISIONS.md`.
- Match the surrounding code's style and comment density.
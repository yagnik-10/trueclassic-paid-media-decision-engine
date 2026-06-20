# AGENTS.md

Guidance for coding agents (Claude Code, Cursor, etc.) working in this repo.
This mirrors `CLAUDE.md`; both are kept in sync.

## Project
True Classic Paid Media Decision Engine — a vendor-neutral decision &
governance layer over Meta + Google media and Shopify commerce truth. Canonical
plan: `docs/FINAL_PLAN.md`. Decisions/deviations: `docs/DECISIONS.md`.

## Build & test
```bash
make setup        # python3.13 venv + EXACT locked deps (requirements-lock.txt)
make setup-dev    # looser pyproject ranges for development
make generate     # regenerate BOTH deterministic datasets (realistic + golden)
make test         # pytest tests/ (hard-pinned to the golden benchmark)
make verify-clean-install   # throwaway venv from the lock, generate + test
```
Keep them green. Tests are deterministic and run in ~1s.

**Dataset profiles (D-034 / D-035).** Two deterministic profiles share the same
latent truth, via `TC_DATASET_PROFILE`. `realistic` is the **PRIMARY/default**
data (volatility + exogenous spend experiments; `data/realistic/`) used by the
engine/API/report. `golden` is the smooth **regression benchmark**
(`data/{raw,canonical}`); the suite hard-pins to it (`tests/conftest.py`). Both
fingerprints are pinned in `tests/test_fingerprints.py`; golden's must not move
unintentionally.

## Conventions
- Python 3.11–3.13. Imports: `import pandera.pandas as pa`, Pydantic v2.
- Determinism: derive RNGs from `config.MASTER_SEED` via
  `np.random.SeedSequence(seed, spawn_key=...)`. Never use the global RNG.
- Schemas are contracts: `schemas/canonical.py` (Pandera) and
  `schemas/envelopes.py` (Pydantic). Nullable columns are deliberate (planted
  defects); don't "fix" them.
- `synth/scenario.py` holds the raw response math/data (config-independent);
  `economics.py` derives the scale floor and latent-truth helpers. Tests assert
  against these; don't duplicate the Hill math in tests.
- Latent generator truth never goes to `data/canonical`/`data/raw` (leakage).
- The scale floor is derived (break-even × safety), not a magic constant.

## Do not
- Add Amazon/Microsoft, Streamlit, Prophet, real OAuth, live writes, or a runtime
  orchestration agent.
- Put numeric decisions in the LLM. The LLM ranks allowed candidates / narrates
  validated output only, always with a deterministic fallback.
- Implement Stage 1–6 work while a task is scoped to an earlier stage. In
  particular Stage 0 has **no** raw→canonical normalization/ingestion (Stage 2)
  and **no** optimizer / allocation search / reserve feasibility (Stage 3/4).
- Change a `config.py` constant without updating the fingerprint test and
  `docs/DECISIONS.md`.

## Stage map
Stage 0 (done): schemas + deterministic generator + defects + invariants.
Stage 1 (done): FastAPI thin shell (`backend/api/`) + Next.js page (`frontend/`) —
one FIXED recommendation + stubbed approve/reject audit. Run with `make api` +
`make web`.
Stage 2 (done): real ingestion (`backend/decision_engine/ingestion/`).
Stage 3 (done): real engine (`backend/decision_engine/engine/`) — XGBoost quantile
BAU forecast + baselines, orthogonalized (double-ML) residualized response, SciPy
SLSQP optimizer with feasibility handling. The recommendation is a real optimizer
result. xgboost needs OpenMP (`brew install libomp`).
Next: Stage 4 trust & business controls (uncertainty charts, calibration
sensitivity, durable approval/audit, reserve modes). See `docs/FINAL_PLAN.md` §11.

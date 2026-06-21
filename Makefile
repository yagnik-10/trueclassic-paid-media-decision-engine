# True Classic Paid Media Decision Engine
# Python 3.13 venv (pinned deps) for the engine; Node (Vite + React) for the web UI.

PYTHON ?= python3.13
VENV   := .venv
BIN    := $(VENV)/bin
PY     := $(BIN)/python
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
PYTHONPATH := .
export PYTHONPATH

.PHONY: help setup setup-dev generate generate-golden generate-realistic test lint lint-report clean fingerprint \
        verify-clean-install api web web-setup model-report econ-report cm-sweep marts

help:
	@echo "make setup      - create venv and install EXACT locked deps (reproducible)"
	@echo "make setup-dev  - create venv and install from pyproject ranges (dev)"
	@echo "make generate   - generate BOTH datasets: realistic (primary) + golden (benchmark)"
	@echo "make generate-realistic - generate only the realistic primary profile (data/realistic/)"
	@echo "make generate-golden    - generate only the golden benchmark (data/{raw,canonical})"
	@echo "make test       - run the test suite (engine + API)"
	@echo "make fingerprint- print + verify the full-artifact fingerprint"
	@echo "make model-report - reproducible forecast/response/optimizer performance report"
	@echo "make marts      - build Looker-ready SQL marts from the audit ledger (DDL + CSV)"
	@echo "make lint       - ruff check (ENFORCING: fails on violations)"
	@echo "make lint-report- ruff check (non-enforcing report)"
	@echo "make verify-clean-install - build a throwaway venv from the lock and run tests"
	@echo "make api        - run the FastAPI backend (http://$(API_HOST):$(API_PORT))"
	@echo "make web-setup  - install web UI (Vite + React) dependencies"
	@echo "make web        - run the Vite dev server (http://localhost:3000)"
	@echo "make clean      - remove generated data and caches"

# Reproducible install: exact locked versions that produce the pinned fingerprint.
setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-lock.txt
	$(BIN)/pip install -e . --no-deps

setup-dev:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

verify-clean-install:
	rm -rf .venv-verify
	$(PYTHON) -m venv .venv-verify
	.venv-verify/bin/pip install --upgrade pip
	.venv-verify/bin/pip install -r requirements-lock.txt
	.venv-verify/bin/pip install -e . --no-deps
	.venv-verify/bin/python scripts/generate_synthetic_data.py --profile golden
	.venv-verify/bin/python scripts/generate_synthetic_data.py --profile realistic
	.venv-verify/bin/pytest tests/
	rm -rf .venv-verify

# Primary onboarding: write BOTH profiles to disk -- realistic (the default the
# engine/API/report use) AND golden (the regression benchmark the test suite pins
# to). The two live in separate folders so neither overwrites the other.
generate: generate-golden generate-realistic

# realistic: PRIMARY data (D-035) -> data/realistic/.
generate-realistic:
	$(PY) scripts/generate_synthetic_data.py --profile realistic

# golden: known-truth benchmark (pinned fingerprint) -> data/{raw,canonical}.
generate-golden:
	$(PY) scripts/generate_synthetic_data.py --profile golden

test:
	$(BIN)/pytest tests/

fingerprint:
	$(PY) scripts/verify_fingerprint.py

# Reproducible model-performance report (forecast + response + optimizer).
# Regenerates from deterministic data without editing sources; run twice for
# identical numeric outputs (metrics.json).
model-report:
	$(PY) scripts/model_report.py

# Contribution-economics report (D-040): per-SKU waterfall, hurdles, sensitivity grid.
econ-report:
	$(PY) scripts/economics_report.py

# Phase-4 CM-ROAS floor policy sweep (D-041, READ-ONLY): grid x modes + model-error
# robustness. Changes no live default/config/fingerprint; decision support only.
cm-sweep:
	$(PY) scripts/cm_floor_sweep.py

# Looker-ready SQL marts (views) over the durable audit ledger -> DDL + CSV extracts.
marts:
	$(PY) scripts/build_marts.py

# --- Web UI: FastAPI backend + Vite/React SPA (frontend/) ---------------
# The web client lives in frontend/ (Vite + React 19 + Tailwind v4). It is a
# read-and-govern client over the API; see docs/DECISIONS.md D-043 for the
# migration off the original Stage-1 Next.js shell.
api:
	$(BIN)/uvicorn backend.api.main:app --reload --host $(API_HOST) --port $(API_PORT)

web-setup:
	cd frontend && npm install

web:
	cd frontend && npm run dev

# Enforcing: non-zero exit on any violation.
lint:
	$(BIN)/ruff check backend tests scripts

# Non-enforcing report (never fails the build).
lint-report:
	$(BIN)/ruff check backend tests scripts --exit-zero

clean:
	rm -rf data/canonical/* data/raw/* data/realistic .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

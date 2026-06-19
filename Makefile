# True Classic Paid Media Decision Engine
# Python 3.13 venv (pinned deps) for the engine; Node for the Next.js shell.

PYTHON ?= python3.13
VENV   := .venv
BIN    := $(VENV)/bin
PY     := $(BIN)/python
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
PYTHONPATH := .
export PYTHONPATH

.PHONY: help setup setup-dev generate test lint lint-report clean fingerprint \
        verify-clean-install api web web-setup

help:
	@echo "make setup      - create venv and install EXACT locked deps (reproducible)"
	@echo "make setup-dev  - create venv and install from pyproject ranges (dev)"
	@echo "make generate   - generate the deterministic synthetic dataset"
	@echo "make test       - run the test suite (engine + API)"
	@echo "make fingerprint- print + verify the full-artifact fingerprint"
	@echo "make lint       - ruff check (ENFORCING: fails on violations)"
	@echo "make lint-report- ruff check (non-enforcing report)"
	@echo "make verify-clean-install - build a throwaway venv from the lock and run tests"
	@echo "make api        - run the FastAPI backend (http://$(API_HOST):$(API_PORT))"
	@echo "make web-setup  - install frontend (Next.js) dependencies"
	@echo "make web        - run the Next.js dev server (http://localhost:3000)"
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
	.venv-verify/bin/python scripts/generate_synthetic_data.py
	.venv-verify/bin/pytest tests/
	rm -rf .venv-verify

generate:
	$(PY) scripts/generate_synthetic_data.py

test:
	$(BIN)/pytest tests/

fingerprint:
	$(PY) scripts/verify_fingerprint.py

# --- Stage 1 thin shell: FastAPI backend + Next.js frontend ----------------
api:
	$(BIN)/uvicorn backend.api.main:app --reload --host $(API_HOST) --port $(API_PORT)

web-setup:
	cd frontend && npm ci

web:
	cd frontend && npm run dev

# Enforcing: non-zero exit on any violation.
lint:
	$(BIN)/ruff check backend tests scripts

# Non-enforcing report (never fails the build).
lint-report:
	$(BIN)/ruff check backend tests scripts --exit-zero

clean:
	rm -rf data/canonical/* data/raw/* .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

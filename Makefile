# True Classic Paid Media Decision Engine — Paid Media Decision Engine
# Stage 0 targets. Python 3.13 venv with pinned deps.

PYTHON ?= python3.13
VENV   := .venv
BIN    := $(VENV)/bin
PY     := $(BIN)/python
PYTHONPATH := .
export PYTHONPATH

.PHONY: help setup setup-dev generate test lint clean fingerprint verify-clean-install

help:
	@echo "make setup      - create venv and install EXACT locked deps (reproducible)"
	@echo "make setup-dev  - create venv and install from pyproject ranges (dev)"
	@echo "make generate   - generate the deterministic synthetic dataset"
	@echo "make test       - run the Stage 0 test suite"
	@echo "make fingerprint- print the combined dataset fingerprint"
	@echo "make lint       - ruff check (ENFORCING: fails on violations)"
	@echo "make lint-report- ruff check (non-enforcing report)"
	@echo "make verify-clean-install - build a throwaway venv from the lock and run tests"
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

# Enforcing: non-zero exit on any violation.
lint:
	$(BIN)/ruff check backend tests scripts

# Non-enforcing report (never fails the build).
lint-report:
	$(BIN)/ruff check backend tests scripts --exit-zero

clean:
	rm -rf data/canonical/* data/raw/* .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

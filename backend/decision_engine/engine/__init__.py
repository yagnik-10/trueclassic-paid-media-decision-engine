"""Stage 3 — the real engine.

Deterministic forecasting + response estimation + SLSQP optimization that
recovers the scenario's marginal economics from the OBSERVABLE canonical data and
replaces the Stage 1 fixed recommendation with a constraint-valid allocation.
No LLM here (Stage 5). Synthetic data verifies the implementation can recover a
known response process; it does not prove causal identification.
"""

"""Reproducible model-performance evaluation harness (read-only over the engine).

This package NEVER modifies the forecasting or response models. It re-imports
their exact feature builder, target, XGBoost configuration, baselines, response
estimator, and optimizer, then runs an independent, leakage-controlled
train/validation/test evaluation and writes a deterministic report. See
``scripts/model_report.py`` and ``make model-report``.
"""

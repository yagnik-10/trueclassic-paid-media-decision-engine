"""Global, deterministic configuration for Stage 0 synthetic generation.

Everything that influences generated numbers is pinned here. Changing any of
these values is a deliberate scenario change and must move the fingerprint
tests in lockstep (see tests/test_fingerprints.py).
"""

from __future__ import annotations

from pathlib import Path

# --- Determinism -----------------------------------------------------------
# Single master seed. All randomness derives from this via numpy Generators
# created with explicit child seeds (see synth/generator.py). Never call the
# global numpy RNG.
MASTER_SEED: int = 20240117

# --- Time window -----------------------------------------------------------
# ~180-270 days of daily data per FINAL_PLAN section 2. We pick 210 days.
N_DAYS: int = 210
START_DATE: str = "2025-01-06"  # a Monday, so day-of-week math is stable

# --- Currency / units ------------------------------------------------------
# Google Ads API reports money in micros (1 unit = 1_000_000 micros). Adapters
# must normalize. We keep the planted normalization defect in raw Google JSON.
MICROS_PER_UNIT: int = 1_000_000

# --- Paths -----------------------------------------------------------------
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = REPO_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
CANONICAL_DIR: Path = DATA_DIR / "canonical"
# Internal, NON-model-input artifacts (latent generator truth). Never loaded by
# adapters, DuckDB, feature discovery, or any model-input path.
INTERNAL_DIR: Path = DATA_DIR / "internal"
LATENT_DIR: Path = INTERNAL_DIR / "latent"

# --- Business policy constants (the truth, not fitted) ---------------------
# These define the golden scenario's decision thresholds. They are referenced
# by invariant tests; the optimizer (Stage 3) will consume them later.
BLENDED_ROAS_FLOOR: float = 4.0          # primary success metric
NC_CPA_TARGET: float = 45.0              # new-customer CPA ceiling ($)
PROSPECTING_MIN_SHARE: float = 0.35      # prospecting floor (share of spend)
MOVEMENT_BOUND: float = 0.20             # +/- per campaign per cycle

# --- Marginal-ROAS scale floor is DERIVED, not a magic number --------------
# The next-dollar scale floor is derived economically from the contribution
# margin (see backend/decision_engine/economics.py):
#     marginal break-even ROAS = 1 / weighted_contribution_margin_rate
#     hard scale floor        = break-even * HARD_FLOOR_SAFETY
# Only the *safety multiplier* is a policy knob here: the hard floor requires the
# next dollar to clear break-even with a small cushion.
# (Efficiency-first hurdles / reserve modes are a later stage — not Stage 0.)
HARD_FLOOR_SAFETY: float = 1.05          # hard scale floor cushion over break-even

# Conservative-policy downside multiplier on marginal ROAS, z at ~P10 of a
# normal. Encodes the Expected (P50) vs Conservative (downside) divergence: a
# campaign near the floor with high noise can clear it at P50 but not at P10.
CONSERVATIVE_Z: float = 1.2816

# Inventory guardrail
INVENTORY_LEAD_TIME_DAYS: int = 14
INVENTORY_SAFETY_DAYS: int = 7

# Label maturity: a 7-day conversion outcome needs 7 days to mature.
LABEL_MATURITY_DAYS: int = 7

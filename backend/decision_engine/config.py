"""Global, deterministic configuration for Stage 0 synthetic generation.

Everything that influences generated numbers is pinned here. Changing any of
these values is a deliberate scenario change and must move the fingerprint
tests in lockstep (see tests/test_fingerprints.py).
"""

from __future__ import annotations

import os
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

# --- Dataset profiles ------------------------------------------------------
# Two DETERMINISTIC profiles share the SAME latent truth (scenario.py) but differ
# in the OBSERVABLE driving process:
#   realistic -- PRIMARY data (D-035): structured volatility + exogenous spend
#                variation; what the engine/API/report use by default. Lives under
#                data/realistic/. Separately fingerprinted (pinned in tests).
#   golden    -- the tight known-truth REGRESSION BENCHMARK (fingerprint pinned);
#                lives at the legacy data/{raw,canonical,internal} paths. The test
#                suite pins itself to golden (tests/conftest.py) regardless of the
#                runtime default, so golden stays the deterministic anchor.
# The active profile is selected via the TC_DATASET_PROFILE env var (default realistic).
PROFILES: tuple[str, ...] = ("golden", "realistic")
DATASET_PROFILE: str = os.environ.get("TC_DATASET_PROFILE", "realistic")

_PROFILE_ROOTS: dict[str, Path] = {
    "golden": DATA_DIR,                 # legacy paths -> golden bytes are untouched
    "realistic": DATA_DIR / "realistic",
}


def profile_root(profile: str | None = None) -> Path:
    """Data root for a dataset profile (defaults to the active TC_DATASET_PROFILE)."""
    p = profile or DATASET_PROFILE
    if p not in _PROFILE_ROOTS:
        raise ValueError(f"unknown dataset profile {p!r}; expected one of {PROFILES}")
    return _PROFILE_ROOTS[p]


def profile_paths(profile: str | None = None) -> dict[str, Path]:
    """Resolve the raw/canonical/internal/latent dirs for a profile (call-time, so
    generation never depends on the import-time active profile)."""
    root = profile_root(profile)
    internal = root / "internal"
    return {"raw": root / "raw", "canonical": root / "canonical",
            "internal": internal, "latent": internal / "latent"}


# Module-level constants resolve to the ACTIVE profile (golden by default), so the
# engine/API/ingestion follow TC_DATASET_PROFILE without per-call wiring.
_ACTIVE = profile_paths()
RAW_DIR: Path = _ACTIVE["raw"]
CANONICAL_DIR: Path = _ACTIVE["canonical"]
# Internal, NON-model-input artifacts (latent generator truth). Never loaded by
# adapters, DuckDB, feature discovery, or any model-input path.
INTERNAL_DIR: Path = _ACTIVE["internal"]
LATENT_DIR: Path = _ACTIVE["latent"]

# --- Business policy constants (the truth, not fitted) ---------------------
# These define the golden scenario's decision thresholds. They are referenced
# by invariant tests; the optimizer (Stage 3) will consume them later.
BLENDED_ROAS_FLOOR: float = 4.0          # primary success metric
NC_CPA_TARGET: float = 45.0              # new-customer CPA ceiling ($)
# Prospecting floor (share of spend) — a brand-investment policy minimum, and it
# is PROFILE-AWARE because the binding physics differ by profile (D-037). The
# prospecting campaigns cap out early (high utilization by design), so their
# daily caps impose a cap-implied CEILING on prospecting share in growth
# (full-budget) mode; the policy floor must sit at/below that ceiling to be
# feasible.
#   golden:    ceiling ~0.335 → 0.33 floor still BINDS (the active constraint),
#              demonstrating the guardrail shapes the plan. (Not 0.35: that
#              would exceed the ceiling and be infeasible.)
#   realistic: caps + the below-hurdle gate on META_ADV_SHOPPING pin prospecting
#              at ~0.319 of the (volatility-/trend-inflated) budget, so a 0.33
#              floor is physically infeasible in growth mode. The floor is set to
#              0.30 — a defensible brand minimum BELOW the ~0.319 ceiling — so the
#              plan is feasible with margin and the prospecting DAILY CAPS (not
#              the policy floor) are the honestly-reported active constraint.
_PROSPECTING_MIN_SHARE_BY_PROFILE: dict[str, float] = {"golden": 0.33, "realistic": 0.30}


def prospecting_min_share(profile: str | None = None) -> float:
    """Profile-aware prospecting-share floor (defaults to the active profile)."""
    return _PROSPECTING_MIN_SHARE_BY_PROFILE[profile or DATASET_PROFILE]


PROSPECTING_MIN_SHARE: float = prospecting_min_share(DATASET_PROFILE)
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

# Forecast horizon: the BAU model predicts a forward window of this many days
# (target_fwd7 = Σ calibrated revenue over t..t+H-1). Numerically equal to the
# maturity gap but a DISTINCT concept; the single source of truth for the "÷ H"
# that converts the 7-day BAU forecast to an average DAILY level for the
# (daily-budget) optimizer anchor. Changing it is a scenario change.
FORECAST_HORIZON_DAYS: int = 7

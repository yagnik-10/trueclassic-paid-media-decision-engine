"""Economics used to characterize and verify the synthetic latent truth.

Stage 0 scope: this module only provides the economics needed to (a) generate
the golden scenario and (b) verify its latent truth — chiefly the *break-even*
and *hard scale-floor* marginal-ROAS thresholds used to describe each channel's
tension. The marginal-ROAS thresholds are NOT magic numbers; they are derived
from the contribution margin:

    marginal break-even ROAS = 1 / contribution_margin_rate
        (the next dollar of spend covers itself out of margin)
    hard scale floor         = break-even * HARD_FLOOR_SAFETY   (small cushion)

NOTE (scope boundary): efficiency-first hurdles, reserve-feasibility, and any
optimizer/allocation policy are Stage 3/4 concerns and deliberately do NOT live
here. Stage 0 only asserts that the scenario *supports* a future feasible
optimization; it never computes one.

This module depends on :mod:`scenario` and :mod:`config`; ``scenario`` itself is
deliberately config-independent so there is no import cycle.
"""

from __future__ import annotations

from backend.decision_engine import config as C
from backend.decision_engine.synth import scenario as S


def break_even_roas(contribution_margin_rate: float) -> float:
    """Marginal ROAS at which the next dollar of spend exactly covers itself."""
    return 1.0 / contribution_margin_rate


def hurdle(contribution_margin_rate: float, safety_multiplier: float) -> float:
    """A risk-adjusted marginal-ROAS hurdle = break-even * safety_multiplier."""
    return break_even_roas(contribution_margin_rate) * safety_multiplier


def weighted_contribution_margin() -> float:
    """Spend-weighted pre-ad contribution margin across the campaign mix.

    Each campaign is weighted by its base spend and attributed its primary SKU's
    contribution-margin rate.
    """
    total = sum(c.base_spend for c in S.CAMPAIGNS)
    weighted = sum(
        c.base_spend * S.PRODUCT_BY_SKU[c.primary_sku].contribution_margin_rate
        for c in S.CAMPAIGNS
    )
    return weighted / total


# Portfolio-weighted, economically-derived scale threshold (single source of
# truth for the scenario's latent-truth verification).
WEIGHTED_CONTRIBUTION_MARGIN: float = weighted_contribution_margin()
BREAKEVEN_ROAS: float = break_even_roas(WEIGHTED_CONTRIBUTION_MARGIN)
HARD_SCALE_FLOOR: float = hurdle(WEIGHTED_CONTRIBUTION_MARGIN, C.HARD_FLOOR_SAFETY)


def conservative_marginal(c: S.Campaign) -> float:
    """Downside (P10-style) marginal ROAS used by the Conservative policy.

    A campaign near the scale floor with high noise can clear the floor at the
    Expected (P50) marginal but not at this downside — which is exactly how
    Expected and Conservative policies will diverge in a later stage.
    """
    return S.hill_marginal_roas(c.base_spend, c) * (1.0 - C.CONSERVATIVE_Z * c.noise_cv)


def scenario_truth_row(c: S.Campaign) -> dict[str, float]:
    """The analytic decision-truth for a campaign at its operating point.

    This is LATENT generator truth (marginal ROAS, capacity-to-floor, noise) — it
    must never reach canonical/model-ready tables. Tests assert directional
    invariants against it; the daily generated data is independently checked to
    be consistent with it.
    """
    s = c.base_spend
    return {
        "campaign_id": c.campaign_id,
        "segment": c.segment,
        "platform_avg_roas": round(S.platform_average_roas(s, c), 4),
        "incremental_avg_roas": round(S.average_incremental_roas(s, c), 4),
        "marginal_roas": round(S.hill_marginal_roas(s, c), 4),
        "incrementality": c.incrementality,
        "base_spend": s,
        "daily_cap": c.daily_cap,
        "utilization": round(s / c.daily_cap, 4),
        "spend_to_hard_floor": round(S.spend_for_marginal(c, HARD_SCALE_FLOOR), 2),
        "conservative_marginal_roas": round(conservative_marginal(c), 4),
        "noise_cv": c.noise_cv,
    }

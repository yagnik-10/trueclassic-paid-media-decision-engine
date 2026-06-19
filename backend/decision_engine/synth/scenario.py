"""The golden scenario: the *known* truth the rest of the system must recover.

This module encodes the deliberately-designed tensions from FINAL_PLAN section 12
as explicit, analytic adstock-Hill response processes per campaign. The data
generator forward-simulates from these curves. NOTHING here is fitted; this is
the ground truth a Stage-3 model would later try to recover.

Allowed in Stage 0: forward-simulating from a known Hill curve to manufacture
truth. NOT done here: fitting Hill curves, optimization, or any learned model.

Response form (normalized geometric adstock so adstocked spend stays on the
same scale as raw spend; at steady state adstocked spend ~= spend):

    a_t = (1 - decay) * spend_t + decay * a_{t-1}
    R(a) = beta * a**alpha / (gamma**alpha + a**alpha)        # Hill saturation

R(a) is the *incremental* (true) revenue from media. Platform-reported revenue
over-states this by 1/incrementality (the calibration registry later corrects
it). gamma is the half-saturation spend: when base spend >> gamma the channel is
saturated (low marginal); when base spend <= gamma there is room to scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

# --- Segments (FINAL_PLAN section 5, Model B) ------------------------------
Segment = Literal[
    "meta_prospecting",
    "meta_retargeting",
    "google_brand",
    "google_nonbrand",
]


# --- Products: 4 real True Classic names, synthetic economics ---------------
@dataclass(frozen=True)
class Product:
    sku_id: str
    product_name: str
    unit_price: float          # DTC selling price
    unit_cost: float           # COGS
    fulfillment_cost: float    # pick/pack/ship
    return_rate: float         # fraction returned

    @property
    def contribution_margin_rate(self) -> float:
        """Pre-ad contribution margin rate used by the optimizer objective."""
        gross = self.unit_price - self.unit_cost - self.fulfillment_cost
        net = gross * (1.0 - self.return_rate)
        return round(net / self.unit_price, 4)


PRODUCTS: tuple[Product, ...] = (
    Product("TC-CREW-BLK", "Black Crew Neck Tee", 30.0, 8.5, 4.0, 0.06),
    Product("TC-POLO-CLS", "Classic Polo", 45.0, 12.0, 4.5, 0.07),
    Product("TC-JOG-BLK", "Black Active Joggers", 65.0, 19.0, 5.5, 0.09),
    Product("TC-CREW-6PK", "Staple Crew 6-Pack", 99.0, 28.0, 7.0, 0.05),
)

# The inventory-constrained SKU (FINAL_PLAN section 12): joggers promoted in
# Google Shopping/PMax but with low days-of-cover.
INVENTORY_CONSTRAINED_SKU: str = "TC-JOG-BLK"


# --- Campaigns & their known response curves -------------------------------
@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    campaign_name: str
    platform: Literal["meta", "google"]
    segment: Segment
    objective: str
    is_prospecting: bool

    # Known Hill response truth (incremental revenue)
    beta: float          # max incremental revenue (saturation asymptote)
    alpha: float         # Hill exponent (slope / cooperativity)
    gamma: float         # half-saturation spend ($/day)
    decay: float         # geometric adstock decay

    base_spend: float    # current daily operating point ($/day)
    daily_cap: float     # daily budget cap ($/day)
    incrementality: float  # incremental / platform-reported  (in (0, 1])
    noise_cv: float      # coefficient of variation of daily noise

    # Primary promoted SKU (for inventory / margin linkage)
    primary_sku: str

    # baseline non-media demand attributed (organic floor) as $/day; this is the
    # confound a Stage-3 control model must residualize out.
    organic_base: float = 0.0


CAMPAIGNS: tuple[Campaign, ...] = (
    # Meta prospecting: must stay funded; caps out early (cap ~= base spend),
    # NC-CPA / prospecting-floor binding. Moderate marginal, noisy.
    Campaign(
        campaign_id="META_PROSPECTING",
        campaign_name="Meta — Broad Prospecting",
        platform="meta",
        segment="meta_prospecting",
        objective="conversions_prospecting",
        is_prospecting=True,
        beta=23940.0, alpha=1.55, gamma=3600.0, decay=0.50,
        base_spend=4000.0, daily_cap=4200.0,
        incrementality=0.80, noise_cv=0.18,
        primary_sku="TC-CREW-BLK", organic_base=1200.0,
    ),
    # Meta Advantage+ Shopping: prospecting-leaning, also funded, caps mid-day.
    Campaign(
        campaign_id="META_ADV_SHOPPING",
        campaign_name="Meta — Advantage+ Shopping",
        platform="meta",
        segment="meta_prospecting",
        objective="advantage_plus_shopping",
        is_prospecting=True,
        beta=18810.0, alpha=1.65, gamma=3100.0, decay=0.50,
        base_spend=3000.0, daily_cap=3900.0,
        incrementality=0.78, noise_cv=0.16,
        primary_sku="TC-CREW-6PK", organic_base=1000.0,
    ),
    # Meta retargeting: high PLATFORM ROAS, saturated (base >> gamma) so low
    # marginal; planted over-attribution (low incrementality). Should decrease.
    Campaign(
        campaign_id="META_RETARGETING",
        campaign_name="Meta — Dynamic Retargeting",
        platform="meta",
        segment="meta_retargeting",
        objective="dynamic_retargeting",
        is_prospecting=False,
        beta=13500.0, alpha=2.2, gamma=650.0, decay=0.60,
        base_spend=4000.0, daily_cap=5500.0,
        incrementality=0.35, noise_cv=0.10,
        primary_sku="TC-POLO-CLS", organic_base=2200.0,
    ),
    # Google brand: high average ROAS, low utilization (cap >> spend), saturated
    # (base >> gamma); partly captures organic (low incrementality). Reinforces
    # "average ROAS is not enough".
    Campaign(
        campaign_id="GOOGLE_BRAND",
        campaign_name="Google — Brand Search",
        platform="google",
        segment="google_brand",
        objective="brand_search_troas",
        is_prospecting=False,
        beta=10500.0, alpha=2.4, gamma=380.0, decay=0.40,
        base_spend=2000.0, daily_cap=5500.0,
        incrementality=0.45, noise_cv=0.09,
        primary_sku="TC-CREW-BLK", organic_base=2600.0,
    ),
    # Google nonbrand: genuine room to scale (base <= gamma, in-support), high
    # marginal, high incrementality. Should increase. Carries the immature /
    # missing-label defect.
    Campaign(
        campaign_id="GOOGLE_NONBRAND",
        campaign_name="Google — Nonbrand Search",
        platform="google",
        segment="google_nonbrand",
        objective="nonbrand_search_troas",
        is_prospecting=False,
        beta=63000.0, alpha=1.5, gamma=6000.0, decay=0.45,
        base_spend=3800.0, daily_cap=9000.0,
        incrementality=0.85, noise_cv=0.14,
        primary_sku="TC-POLO-CLS", organic_base=700.0,
    ),
    # Google PMax: attractive marginal economics, frequent noon cap-outs
    # (cap ~= base), promotes the INVENTORY-CONSTRAINED SKU (blocks scale-up).
    Campaign(
        campaign_id="GOOGLE_PMAX",
        campaign_name="Google — Performance Max",
        platform="google",
        segment="google_nonbrand",
        objective="pmax_troas",
        is_prospecting=False,
        beta=22230.0, alpha=1.6, gamma=3100.0, decay=0.45,
        base_spend=2800.0, daily_cap=3100.0,
        incrementality=0.82, noise_cv=0.13,
        primary_sku="TC-JOG-BLK", organic_base=600.0,
    ),
    # Google Shopping: attractive economics, caps out; healthy SKU.
    Campaign(
        campaign_id="GOOGLE_SHOPPING",
        campaign_name="Google — Shopping",
        platform="google",
        segment="google_nonbrand",
        objective="shopping_troas",
        is_prospecting=False,
        beta=17100.0, alpha=1.6, gamma=2500.0, decay=0.45,
        base_spend=2200.0, daily_cap=2600.0,
        incrementality=0.80, noise_cv=0.12,
        primary_sku="TC-CREW-6PK", organic_base=500.0,
    ),
)

CAMPAIGN_BY_ID: dict[str, Campaign] = {c.campaign_id: c for c in CAMPAIGNS}
PRODUCT_BY_SKU: dict[str, Product] = {p.sku_id: p for p in PRODUCTS}


# --- Analytic truth functions (no fitting) ---------------------------------
def hill_revenue(spend: float | np.ndarray, c: Campaign) -> float | np.ndarray:
    """Incremental revenue R(a) at steady-state adstock (a ~= spend)."""
    s = np.asarray(spend, dtype=float)
    return c.beta * s**c.alpha / (c.gamma**c.alpha + s**c.alpha)


def hill_marginal_roas(spend: float, c: Campaign) -> float:
    """dR/ds at steady-state adstock: the next-dollar incremental ROAS."""
    s = float(spend)
    num = c.beta * c.alpha * (c.gamma**c.alpha) * s ** (c.alpha - 1.0)
    den = (c.gamma**c.alpha + s**c.alpha) ** 2
    return float(num / den)


def average_incremental_roas(spend: float, c: Campaign) -> float:
    """R(s)/s — incremental average ROAS."""
    s = float(spend)
    return float(hill_revenue(s, c) / s)


def platform_average_roas(spend: float, c: Campaign) -> float:
    """What the platform *reports*: incremental revenue inflated by 1/incrementality."""
    return average_incremental_roas(spend, c) / c.incrementality


def spend_for_marginal(c: Campaign, floor: float) -> float:
    """Spend level at which marginal ROAS equals ``floor``.

    Solved by monotone bisection on the (decreasing-past-peak) marginal curve.
    Used to size 'capacity to a hurdle' for the efficiency-reserve calculation.
    """
    lo, hi = 1.0, max(c.daily_cap * 4, c.gamma * 8)
    # If even at base spend marginal is already below the floor, capacity is the
    # pull-back point; bisection still finds the crossing on the falling side.
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if hill_marginal_roas(mid, c) > floor:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)

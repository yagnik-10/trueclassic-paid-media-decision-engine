"""API service for the thin Buyer & Inventory beat (FINAL_PLAN §9).

Read-only. Surfaces the canonical ``fact_inventory_snapshot`` (units, demand,
days-of-cover, stockout risk) joined to the media campaigns each SKU sells, plus
a deterministic, documented reorder suggestion. It computes nothing the engine
doesn't already enforce: ``no_scale`` reuses the exact ``stockout_risk`` set the
optimizer pins (see ``engine.recommend._context``), so the buyer view and the
recommendation's ``inventory_no_scale`` risk flags can never disagree.

This is intentionally a single planner card's worth of data — NOT a second
inventory/replenishment product. Lead-time/safety-day coverage is the policy;
incoming/open POs are not in the synthetic data, so the reorder quantity is
explicitly labelled as assuming none.
"""

from __future__ import annotations

import math
from datetime import timedelta
from functools import lru_cache

import pandas as pd

from backend.api.schemas import (
    BuyerCampaignLink,
    BuyerInventoryItem,
    BuyerInventoryResponse,
)
from backend.decision_engine.engine.recommend import _context
from backend.decision_engine.synth.generator import generate

REORDER_POLICY = (
    "Order-up-to (lead_time + safety_days) x forecast_daily_demand minus units_on_hand. "
    "Assumes incoming/open POs = 0."
)


def _urgency(days_of_cover: float, threshold_days: float, stockout_risk: bool) -> str:
    """Stockout-risk SKUs are urgent; a comfortable buffer above the guardrail is
    monitor-only; the band just above the guardrail is reorder-soon."""
    if stockout_risk or days_of_cover < threshold_days:
        return "urgent"
    if days_of_cover < threshold_days * 1.5:
        return "reorder_soon"
    return "monitor"


@lru_cache(maxsize=1)
def buyer_inventory() -> BuyerInventoryResponse:
    # Reuse the engine context so the SKU->campaign linkage and the no-scale set are
    # byte-identical to what the recommendation flags as inventory_no_scale.
    ctx = _context()
    inv = generate().tables["fact_inventory_snapshot"]
    dim_sku = ctx.dim_sku            # indexed by sku_id (has product_name)
    dim_c = ctx.dim_c                # indexed by campaign_id (name, platform)

    # Invert the engine's campaign -> sku map into sku -> [campaign links].
    sku_campaigns: dict[str, list[BuyerCampaignLink]] = {}
    for cid, sku in sorted(ctx.sku_of.items()):
        sku_campaigns.setdefault(str(sku), []).append(
            BuyerCampaignLink(
                campaign_id=str(cid),
                campaign_name=str(dim_c.loc[cid, "campaign_name"]),
                platform=str(dim_c.loc[cid, "platform"]),
            )
        )

    snapshot_date = pd.to_datetime(inv["date"]).max()
    items: list[BuyerInventoryItem] = []
    for row in inv.sort_values("sku_id").itertuples(index=False):
        units = int(row.units_on_hand)
        demand = float(row.forecast_daily_demand)
        doc = float(row.days_of_cover)
        lead = int(row.lead_time_days)
        safety = int(row.safety_days)
        threshold = lead + safety
        stockout = bool(row.stockout_risk)

        stockout_date = (snapshot_date + timedelta(days=math.floor(doc))).date().isoformat()
        order_up_to = threshold * demand
        reorder_qty = max(0, math.ceil(order_up_to - units))

        product_name = (
            str(dim_sku.loc[row.sku_id, "product_name"])
            if row.sku_id in dim_sku.index else str(row.sku_id)
        )
        items.append(BuyerInventoryItem(
            sku_id=str(row.sku_id), product_name=product_name,
            units_on_hand=units, forecast_daily_demand=round(demand, 2),
            days_of_cover=round(doc, 1), lead_time_days=lead, safety_days=safety,
            stockout_risk=stockout, no_scale=stockout,
            estimated_stockout_date=stockout_date,
            reorder_qty=reorder_qty,
            reorder_assumption="assumes incoming/open POs = 0; targets lead-time + safety-day coverage",
            urgency=_urgency(doc, threshold, stockout),
            linked_campaigns=sku_campaigns.get(str(row.sku_id), []),
        ))

    return BuyerInventoryResponse(
        snapshot_date=snapshot_date.date().isoformat(),
        reorder_policy=REORDER_POLICY,
        items=items,
    )

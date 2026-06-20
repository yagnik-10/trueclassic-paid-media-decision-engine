"""Deterministic synthetic-data generator → the 13 canonical tables.

Forward-simulates daily campaign data from the known adstock-Hill processes in
scenario.py, derives the Shopify commerce truth and inventory snapshot, builds
the calibration registry, and injects the 11 planted defects (defects.py).

Determinism contract: all randomness comes from numpy Generators seeded with
explicit child seeds derived from config.MASTER_SEED via SeedSequence. The
global RNG is never touched. Same seed -> byte-identical canonical CSVs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.decision_engine import config as C
from backend.decision_engine.synth import scenario as S
from backend.decision_engine.synth.defects import IssueLog

# Per-platform unit economics for deriving clicks/impressions from spend.
_PLATFORM_CPC = {"meta": 0.95, "google": 1.35}
_PLATFORM_CTR = {"meta": 0.012, "google": 0.045}
# New-customer share of conversions by segment (prospecting buys new customers).
_NEW_CUST_RATE = {
    "meta_prospecting": 0.72,
    "meta_retargeting": 0.18,
    "google_brand": 0.22,
    "google_nonbrand": 0.55,
}
# Canonical attribution window per platform; one campaign is intentionally off.
_ATTR_WINDOW = {"meta": "7d_click_1d_view", "google": "data_driven"}


@dataclass
class Dataset:
    """All canonical frames plus the scenario truth and defect bookkeeping."""

    tables: dict[str, pd.DataFrame]
    scenario_truth: pd.DataFrame
    defect_counts: dict[str, int]
    raw: dict[str, object] = field(default_factory=dict)  # raw API envelopes


def _rng(seed: int, *path: int) -> np.random.Generator:
    """A reproducible Generator seeded by ``seed`` plus a fixed spawn path."""
    return np.random.default_rng(np.random.SeedSequence(seed, spawn_key=path))


def _dates() -> pd.DatetimeIndex:
    return pd.date_range(C.START_DATE, periods=C.N_DAYS, freq="D")


def _calendar_factors(dates: pd.DatetimeIndex, profile: str = "golden") -> dict[str, np.ndarray]:
    """Deterministic day-of-week, trend and promo multipliers (the confound).

    The ``realistic`` profile layers stronger weekly amplitude, an annual seasonal
    swing, and more (and larger) promo/holiday windows on top of the same baseline.
    """
    dow = dates.dayofweek.to_numpy()
    # weekend lift for DTC apparel
    dow_factor = np.where(dow >= 5, 1.18, 1.0) * np.where(dow == 0, 0.92, 1.0)
    t = np.arange(len(dates))
    trend = 1.0 + 0.0006 * t  # mild growth over the window
    # two deterministic promo windows (e.g. a sale weekend each)
    promo = np.ones(len(dates))
    promo[40:47] = 1.45
    promo[150:158] = 1.55
    if profile == "realistic":
        # stronger, asymmetric weekly shape (Fri/Sat/Sun peak, Mon trough)
        dow_factor = (np.where(dow >= 5, 1.30, 1.0) * np.where(dow == 4, 1.10, 1.0)
                      * np.where(dow == 0, 0.85, 1.0))
        # annual seasonality (~+/-12%) so the model must learn a real seasonal signal
        trend = trend * (1.0 + 0.12 * np.sin(2 * np.pi * (t + 10) / 365.25))
        # more frequent + holiday-scale promo windows (the big real-world driver)
        for lo, hi, lift in ((20, 25, 1.35), (40, 47, 1.55), (88, 93, 1.40),
                             (150, 158, 1.70), (188, 196, 1.85)):
            promo[lo:hi] = lift
    promo_flag = (promo > 1.0)
    return {"dow": dow_factor, "trend": trend, "promo": promo, "promo_flag": promo_flag}


# Realistic profile: campaigns that ran EXOGENOUS budget experiments (staggered
# +/-15/30% steps + washouts uncorrelated with demand) -> their Hill response is
# identifiable. The rest stay purely observational (narrow, confounded support) so
# per-campaign recovery honestly tracks whether that campaign had identifying
# variation. (Decision-relevant mix; never used by the golden profile.)
_EXPERIMENTAL_CAMPAIGNS = {"GOOGLE_NONBRAND", "META_PROSPECTING", "GOOGLE_PMAX"}
_INTERVENTION_OFFSET = {"GOOGLE_NONBRAND": 0, "META_PROSPECTING": 17, "GOOGLE_PMAX": 33}
_INTERVENTION_STEPS = ((30, 55, 1.30), (70, 95, 0.70), (110, 135, 1.15), (160, 185, 0.85))
_WASHOUT_WINDOWS = ((96, 100), (143, 147))


def _intervention_schedule(campaign_id: str, n: int) -> np.ndarray:
    """Deterministic exogenous budget-step multiplier (1.0 if not experimental)."""
    m = np.ones(n)
    if campaign_id not in _EXPERIMENTAL_CAMPAIGNS:
        return m
    off = _INTERVENTION_OFFSET[campaign_id]
    for lo, hi, lift in _INTERVENTION_STEPS:
        s = (lo + off) % n
        m[s:min(s + (hi - lo), n)] = lift
    return m


def _apply_washouts(campaign_id: str, target: np.ndarray) -> np.ndarray:
    """Short near-pause windows (experimental campaigns) so adstock decay is identified."""
    if campaign_id not in _EXPERIMENTAL_CAMPAIGNS:
        return target
    t = target.copy()
    for lo, hi in _WASHOUT_WINDOWS:
        t[lo:hi] *= 0.15
    return t


def _simulate_campaign(c: S.Campaign, dates: pd.DatetimeIndex,
                       cal: dict[str, np.ndarray], rng: np.random.Generator,
                       profile: str = "golden",
                       rrng: np.random.Generator | None = None) -> pd.DataFrame:
    n = len(dates)
    # Target spend before capping: operating point modulated by calendar + noise.
    noise = rng.normal(1.0, c.noise_cv, n).clip(0.4, 1.8)
    target = c.base_spend * cal["dow"] * cal["trend"] * (1.0 + 0.25 * (cal["promo"] - 1.0)) * noise
    if profile == "realistic":
        # exogenous budget experiments + wider/heteroscedastic operating noise +
        # adstock washouts (all from an INDEPENDENT stream; golden draws untouched).
        interv = _intervention_schedule(c.campaign_id, n)
        op_noise = rrng.normal(1.0, max(c.noise_cv, 0.10), n).clip(0.3, 2.2)
        target = (c.base_spend * cal["dow"] * cal["trend"]
                  * (1.0 + 0.25 * (cal["promo"] - 1.0)) * interv * op_noise)
        target = _apply_washouts(c.campaign_id, target)
    spend = np.minimum(target, c.daily_cap)
    cap_hit = target > c.daily_cap

    # Normalized geometric adstock (weights sum to 1 -> adstocked ~ spend scale).
    a = np.empty(n)
    prev = c.base_spend
    for i in range(n):
        prev = (1.0 - c.decay) * spend[i] + c.decay * prev
        a[i] = prev

    incr_rev = np.asarray(S.hill_revenue(a, c))
    if profile == "realistic":
        # heteroscedastic, mean-preserving revenue noise (noisier at low utilization)
        # + sparse two-sided shocks. Kept below the identifiability-break point.
        util = spend / max(c.daily_cap, 1.0)
        sigma = (0.12 + 0.10 * (1.0 - np.clip(util, 0.0, 1.0))).astype(float)
        rev_noise = rrng.lognormal(-0.5 * sigma * sigma, sigma)
        hit = rrng.random(n) < 0.04
        shock = np.where(rrng.random(n) < 0.5, 1.8, 1.0 / 1.8)
        rev_noise = np.where(hit, rev_noise * shock, rev_noise).clip(0.4, 2.5)
    else:
        rev_noise = rng.normal(1.0, 0.05, n).clip(0.7, 1.3)
    incr_rev = incr_rev * rev_noise
    organic = c.organic_base * cal["dow"] * cal["promo"]

    # Platform over/under-reports incremental by 1/incrementality.
    platform_rev = incr_rev / c.incrementality * rng.normal(1.0, 0.03, n).clip(0.8, 1.2)

    sku = S.PRODUCT_BY_SKU[c.primary_sku]
    platform_conv = platform_rev / sku.unit_price
    new_cust = platform_conv * _NEW_CUST_RATE[c.segment]

    cpc = _PLATFORM_CPC[c.platform] * rng.normal(1.0, 0.06, n).clip(0.6, 1.6)
    ctr = _PLATFORM_CTR[c.platform] * rng.normal(1.0, 0.08, n).clip(0.4, 1.8)
    clicks = np.maximum(1.0, spend / cpc)
    impressions = np.maximum(clicks, clicks / ctr)

    return pd.DataFrame(
        {
            "date": dates,
            "campaign_id": c.campaign_id,
            "platform": c.platform,
            "segment": c.segment,
            "sku_id": c.primary_sku,
            "spend": np.round(spend, 2),
            "impressions": impressions.round().astype("int64"),
            "clicks": clicks.round().astype("int64"),
            "platform_reported_revenue": np.round(platform_rev, 2),
            "platform_reported_conversions": np.round(platform_conv, 2),
            "new_customers": np.round(new_cust, 2),
            "attribution_window": _ATTR_WINDOW[c.platform],
            "label_mature": True,
            "extraction_date": dates.max(),
            "is_duplicate": False,
            # carried for downstream truth, not part of canonical schema:
            "_incremental_revenue": np.round(incr_rev, 2),
            "_organic_revenue": np.round(organic, 2),
            "_cap_hit": cap_hit,
        }
    )


def _build_dim_campaign() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "campaign_id": c.campaign_id,
                "campaign_name": c.campaign_name,
                "platform": c.platform,
                "segment": c.segment,
                "objective": c.objective,
                "is_prospecting": c.is_prospecting,
                "daily_cap": c.daily_cap,
            }
            for c in S.CAMPAIGNS
        ]
    )


def _build_dim_sku() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sku_id": p.sku_id,
                "product_name": p.product_name,
                "unit_price": p.unit_price,
                "unit_cost": p.unit_cost,
                "fulfillment_cost": p.fulfillment_cost,
                "return_rate": p.return_rate,
                "contribution_margin_rate": p.contribution_margin_rate,
            }
            for p in S.PRODUCTS
        ]
    )


def _build_commerce_truth(fact: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Shopify DTC source of record: true (incremental + organic) revenue per SKU-day."""
    g = (
        fact.groupby(["date", "sku_id"], as_index=False)
        .agg(true_rev=("_incremental_revenue", "sum"), organic=("_organic_revenue", "sum"))
    )
    g["dtc_revenue"] = (g["true_rev"] + g["organic"]).round(2)
    prices = {p.sku_id: p.unit_price for p in S.PRODUCTS}
    g["dtc_orders"] = (g["dtc_revenue"] / g["sku_id"].map(prices)).round().astype("int64")
    # New vs returning split (deterministic, sku-dependent)
    nc_share = g["sku_id"].map(
        {"TC-CREW-BLK": 0.45, "TC-POLO-CLS": 0.35, "TC-JOG-BLK": 0.5, "TC-CREW-6PK": 0.4}
    ).to_numpy()
    g["new_customer_revenue"] = (g["dtc_revenue"] * nc_share).round(2)
    g["returning_customer_revenue"] = (g["dtc_revenue"] - g["new_customer_revenue"]).round(2)
    return g[["date", "sku_id", "dtc_orders", "dtc_revenue",
              "new_customer_revenue", "returning_customer_revenue"]]


def _build_inventory(dates: pd.DatetimeIndex, commerce: pd.DataFrame) -> pd.DataFrame:
    """End-of-window inventory snapshot per SKU. One SKU is stockout-constrained."""
    rows = []
    snap_date = dates.max()
    demand = (
        commerce.groupby("sku_id")["dtc_orders"].mean().to_dict()
    )
    threshold_days = C.INVENTORY_LEAD_TIME_DAYS + C.INVENTORY_SAFETY_DAYS  # 21
    # Target days-of-cover: exactly one SKU (the joggers) is below the guardrail
    # threshold; the rest carry a comfortable buffer above it.
    target_doc = {
        "TC-CREW-BLK": 30,
        "TC-POLO-CLS": 30,
        "TC-JOG-BLK": 4,      # constrained: well below the 21-day threshold
        "TC-CREW-6PK": 32,
    }
    for sku, daily_demand in demand.items():
        units = int(round(max(daily_demand, 1e-6) * target_doc[sku]))
        doc = units / max(daily_demand, 1e-6)
        rows.append(
            {
                "date": snap_date,
                "sku_id": sku,
                "units_on_hand": int(units),
                "forecast_daily_demand": round(float(daily_demand), 4),
                "lead_time_days": C.INVENTORY_LEAD_TIME_DAYS,
                "safety_days": C.INVENTORY_SAFETY_DAYS,
                "days_of_cover": round(float(doc), 2),
                "stockout_risk": bool(doc < threshold_days),
            }
        )
    return pd.DataFrame(rows).sort_values("sku_id").reset_index(drop=True)


def _build_calibration_registry() -> pd.DataFrame:
    """Synthetic incrementality coefficients per segment (provenance + confidence)."""
    sources = {
        "meta_prospecting": ("geo_lift_synth", "high"),
        "meta_retargeting": ("conversion_lift_synth", "high"),
        "google_brand": ("mmm_synth", "medium"),
        "google_nonbrand": ("geo_lift_synth", "high"),
    }
    # one coefficient per segment, taken from the scenario truth's incrementality
    seg_incr: dict[str, float] = {}
    for c in S.CAMPAIGNS:
        seg_incr.setdefault(c.segment, c.incrementality)
    rows = []
    for i, (seg, coef) in enumerate(seg_incr.items(), start=1):
        src, conf = sources[seg]
        rows.append(
            {
                "registry_id": f"CAL-{i:03d}",
                "segment": seg,
                "coefficient": round(float(coef), 4),
                "source": src,
                "effective_start": pd.Timestamp(C.START_DATE),
                "effective_end": pd.NaT,
                "confidence": conf,
                "scope": "segment_level",
                "is_synthetic": True,
            }
        )
    return pd.DataFrame(rows)


def _build_sku_alias(log: IssueLog) -> pd.DataFrame:
    """Platform product-id ↔ canonical SKU map, incl. planted alias defects."""
    rows: list[dict] = []
    # Clean auto-matches: each platform exposes a recognizable id per SKU.
    id_templates = {"meta": "FB_{}", "google": "GG_{}"}
    for plat, tmpl in id_templates.items():
        for p in S.PRODUCTS:
            rows.append(
                {
                    "platform": plat,
                    "platform_product_id": tmpl.format(p.sku_id),
                    "sku_id": p.sku_id,
                    "match_status": "auto_matched",
                    "confidence": 0.99,
                }
            )

    # Defect: 2 mismatched aliases — low-confidence fuzzy auto-matches.
    mismatches = [
        ("meta", "FB_TCCREWBLK_V2", "TC-CREW-BLK"),
        ("google", "GG_POLO_CLASSIC", "TC-POLO-CLS"),
    ]
    for plat, pid, sku in mismatches:
        rows.append({"platform": plat, "platform_product_id": pid, "sku_id": sku,
                     "match_status": "auto_matched", "confidence": 0.61})
        log.add("sku_alias_mismatch", "sku_alias", pid,
                f"low-confidence fuzzy match {pid} -> {sku}")

    # Defect: 1 similar-but-wrong candidate requiring human approval.
    rows.append({"platform": "google", "platform_product_id": "GG_TC-JOG-BLU",
                 "sku_id": "TC-JOG-BLK", "match_status": "needs_approval", "confidence": 0.58})
    log.add("sku_candidate_needs_approval", "sku_alias", "GG_TC-JOG-BLU",
            "candidate GG_TC-JOG-BLU resembles TC-JOG-BLK (blue vs black) — approval required")

    # Defect: 1 unknown product id requiring quarantine.
    rows.append({"platform": "meta", "platform_product_id": "FB_UNMAPPED_99X",
                 "sku_id": None, "match_status": "quarantined", "confidence": 0.0})
    log.add("unknown_sku_quarantine", "sku_alias", "FB_UNMAPPED_99X",
            "unknown platform product id — quarantined until mapped")

    return pd.DataFrame(rows)


def _apply_fact_defects(fact: pd.DataFrame, log: IssueLog,
                        rng: np.random.Generator) -> pd.DataFrame:
    """Realize the fact-table-level planted defects in place and register them."""
    fact = fact.sort_values(["campaign_id", "date"]).reset_index(drop=True)

    # --- Defect: natural label-maturity tail (policy, NOT a counted defect) ---
    cutoff = fact["date"].max() - pd.Timedelta(days=C.LABEL_MATURITY_DAYS)
    fact.loc[fact["date"] > cutoff, "label_mature"] = False

    # --- Defect 8: 4 extra immature labels mid-series on GOOGLE_NONBRAND ---
    nb = fact.index[fact["campaign_id"] == "GOOGLE_NONBRAND"].to_numpy()
    immature_idx = nb[[60, 61, 95, 96]]
    fact.loc[immature_idx, "label_mature"] = False
    for ix in immature_idx:
        log.add("immature_conversion_labels", "fact_ad_performance",
                f"GOOGLE_NONBRAND@{fact.loc[ix, 'date'].date()}",
                "conversion label not matured at extraction time")

    # --- Defect 2: 3 Google rows missing extraction date ---
    gg = fact.index[fact["platform"] == "google"].to_numpy()
    miss_idx = gg[[10, 11, 12]]
    fact.loc[miss_idx, "extraction_date"] = pd.NaT
    for ix in miss_idx:
        log.add("missing_google_extraction_date", "fact_ad_performance",
                f"{fact.loc[ix, 'campaign_id']}@{fact.loc[ix, 'date'].date()}",
                "extraction date missing — flag, do not impute")

    # --- Defect 7: 5 null new-customer values ---
    pr = fact.index[fact["campaign_id"] == "META_PROSPECTING"].to_numpy()
    null_idx = pr[[5, 6, 7, 8, 9]]
    fact.loc[null_idx, "new_customers"] = np.nan
    for ix in null_idx:
        log.add("null_new_customer_value", "fact_ad_performance",
                f"META_PROSPECTING@{fact.loc[ix, 'date'].date()}",
                "new-customer value null — impute low-confidence")

    # --- Defect 9: attribution-window mismatch on GOOGLE_BRAND ---
    fact.loc[fact["campaign_id"] == "GOOGLE_BRAND", "attribution_window"] = "last_click"
    log.add("attribution_window_mismatch", "dim_campaign", "GOOGLE_BRAND",
            "GOOGLE_BRAND reports last_click; canonical window is data_driven")

    # --- Defect 11: inconsistent date coverage — drop a 7-day block ---
    gap_mask = (
        (fact["campaign_id"] == "META_ADV_SHOPPING")
        & (fact["date"] >= fact["date"].min() + pd.Timedelta(days=70))
        & (fact["date"] < fact["date"].min() + pd.Timedelta(days=77))
    )
    fact = fact.loc[~gap_mask].reset_index(drop=True)
    log.add("inconsistent_date_coverage", "fact_ad_performance", "META_ADV_SHOPPING",
            "7-day coverage gap (days 70-76) — flag coverage gap")

    # --- Defect 1: duplicate Meta record ---
    dup_src = fact.index[fact["campaign_id"] == "META_RETARGETING"].to_numpy()[100]
    dup_row = fact.loc[[dup_src]].copy()
    dup_row["is_duplicate"] = True
    fact = pd.concat([fact, dup_row], ignore_index=True)
    log.add("duplicate_meta_record", "fact_ad_performance",
            f"META_RETARGETING@{dup_row['date'].iloc[0].date()}",
            "exact duplicate Meta insight row — dedupe on natural key")

    # --- Defect 3: cost_micros normalization (feed-level notice) ---
    log.add("google_cost_micros_normalization", "raw_google_feed", "metrics.cost_micros",
            "Google cost reported in micros — divide by 1e6 on ingest")

    # --- Defect 10: platform revenue exceeds Shopify DTC (retargeting over-attr) ---
    log.add("platform_revenue_exceeds_shopify", "fact_commerce_truth", "TC-POLO-CLS",
            "Meta retargeting over-reports revenue for TC-POLO-CLS vs Shopify DTC")

    return fact


def _apply_commerce_defects(commerce: pd.DataFrame, fact: pd.DataFrame,
                            log: IssueLog) -> pd.DataFrame:
    """Null 5 new-customer revenue values to match the fact-table null defect.

    (Registered under the fact-table null defect; not double-counted here.)
    """
    idx = commerce.index[commerce["sku_id"] == "TC-CREW-BLK"].to_numpy()[3:8]
    commerce.loc[idx, "new_customer_revenue"] = np.nan
    return commerce


def generate(seed: int = C.MASTER_SEED, profile: str | None = None) -> Dataset:
    """Generate the full canonical dataset deterministically from ``seed``.

    ``profile`` selects the observable driving process (``golden`` = the smooth
    known-truth benchmark; ``realistic`` = structured volatility + exogenous spend
    variation). The latent truth (scenario.py response/incrementality) is identical
    across profiles, so known-truth grading stays valid. Defaults to the active
    ``TC_DATASET_PROFILE``.
    """
    profile = profile or C.DATASET_PROFILE
    dates = _dates()
    cal = _calendar_factors(dates, profile)
    log = IssueLog()

    # Per-campaign simulation with independent, reproducible child streams. The
    # realistic profile draws its extra volatility from a SEPARATE stream (spawn
    # path 1000+i) so the golden draw sequence is byte-for-byte unchanged.
    frames = [
        _simulate_campaign(c, dates, cal, _rng(seed, i), profile,
                           _rng(seed, 1000 + i) if profile == "realistic" else None)
        for i, c in enumerate(S.CAMPAIGNS)
    ]
    fact_full = pd.concat(frames, ignore_index=True)

    # Commerce truth from the pre-defect truth columns.
    commerce = _build_commerce_truth(fact_full, _rng(seed, 900))
    commerce = _apply_commerce_defects(commerce, fact_full, log)

    # Inventory from commerce demand.
    inventory = _build_inventory(dates, commerce)

    # Apply fact-level defects, then drop the private truth columns.
    fact = _apply_fact_defects(fact_full.copy(), log, _rng(seed, 800))
    fact = fact.drop(columns=[c for c in fact.columns if c.startswith("_")])

    sku_alias = _build_sku_alias(log)
    dq = pd.DataFrame(log.rows)

    # Scenario truth (analytic decision facts) for invariant tests. LATENT — not
    # part of the canonical tables; persisted only under data/internal/latent.
    from backend.decision_engine.economics import scenario_truth_row

    truth = pd.DataFrame([scenario_truth_row(c) for c in S.CAMPAIGNS])

    from backend.decision_engine.schemas.canonical import OPERATIONAL_TABLES, empty_frame

    tables: dict[str, pd.DataFrame] = {
        "fact_ad_performance": fact,
        "dim_campaign": _build_dim_campaign(),
        "dim_sku": _build_dim_sku(),
        "sku_alias": sku_alias,
        "fact_commerce_truth": commerce,
        "fact_inventory_snapshot": inventory,
        "data_quality_issue": dq,
        "calibration_registry": _build_calibration_registry(),
    }
    for t in OPERATIONAL_TABLES:
        tables[t] = empty_frame(t)

    return Dataset(tables=tables, scenario_truth=truth, defect_counts=log.counts)

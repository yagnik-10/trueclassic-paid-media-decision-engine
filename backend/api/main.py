"""FastAPI app — the Stage 1 thin shell: recommendation + approve/reject + audit."""

from __future__ import annotations

import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.api import ingestion_service
from backend.api.calibration_service import registry as calibration_registry
from backend.api.ingestion_service import SkuApprovalError
from backend.api.marts import MART_NAMES
from backend.api.recommendation import build_recommendation
from backend.api.schemas import (
    AuditChainStatus,
    CalibrationRegistryResponse,
    ConstraintParams,
    DecisionRequest,
    DecisionResponse,
    IngestionSummary,
    Recommendation,
    SkuApprovalRequest,
    SkuResolutionItem,
)
from backend.api.store import (
    DEFAULT_AUDIT_DB,
    DecisionConflict,
    DurableDecisionStore,
    SnapshotStore,
)
from backend.decision_engine.calibration.registry import apply_overrides, calibration_map
from backend.decision_engine.config import (
    BLENDED_ROAS_FLOOR,
    MOVEMENT_BOUND,
    NC_CPA_TARGET,
    PROSPECTING_MIN_SHARE,
)
from backend.decision_engine.engine.recommend import engine_provenance

app = FastAPI(
    title="True Classic Paid Media Decision Engine — API",
    description="Decision engine: optimizer recommendation + adjustable constraints + audit.",
    version="0.3.0",
)

# The Next.js dev server runs on :3000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

store = DurableDecisionStore(os.environ.get("TC_AUDIT_DB", DEFAULT_AUDIT_DB))
snapshots = SnapshotStore()


def _parse_calibration_overrides(raw: str | None) -> dict[str, float]:
    """JSON object of segment → coefficient for sensitivity what-ifs."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"calibration_overrides: invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="calibration_overrides must be a JSON object")
    try:
        apply_overrides(calibration_map(), parsed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {str(k): float(v) for k, v in parsed.items()}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": "1"}


@app.get("/api/ingestion", response_model=IngestionSummary)
def get_ingestion() -> IngestionSummary:
    return ingestion_service.summary()


@app.get("/api/calibration/registry", response_model=CalibrationRegistryResponse)
def get_calibration_registry() -> CalibrationRegistryResponse:
    return calibration_registry()


@app.post("/api/sku-resolution/{platform_product_id}/approve",
          response_model=SkuResolutionItem)
def approve_sku(platform_product_id: str, body: SkuApprovalRequest) -> SkuResolutionItem:
    try:
        return ingestion_service.approve_sku(platform_product_id, body.sku_id)
    except SkuApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/recommendation", response_model=Recommendation)
def get_recommendation(
    policy: Literal["expected", "conservative"] = "expected",
    roas_floor: float = Query(default=BLENDED_ROAS_FLOOR, ge=1.0, le=10.0),
    nc_cpa_target: float = Query(default=NC_CPA_TARGET, ge=5.0, le=200.0),
    prospecting_min_share: float = Query(default=PROSPECTING_MIN_SHARE, ge=0.0, le=0.80),
    movement_bound: float = Query(default=MOVEMENT_BOUND, ge=0.05, le=0.40),
    reserve_mode: Literal["growth", "efficiency_first"] = "growth",
    calibration_overrides: str | None = Query(
        default=None,
        description='JSON object of segment→coefficient overrides, e.g. {"meta_retargeting":0.4}',
    ),
) -> Recommendation:
    """Solve the optimizer for the (validated, adjustable) constraints — fast (context
    cached) — and store the immutable scenario snapshot for later approval."""
    cp = ConstraintParams(
        roas_floor=roas_floor, nc_cpa_target=nc_cpa_target,
        prospecting_min_share=prospecting_min_share, movement_bound=movement_bound,
        reserve_mode=reserve_mode,
        calibration_overrides=_parse_calibration_overrides(calibration_overrides),
    )
    # store (first write wins) and return the CANONICAL snapshot, so the displayed
    # plan is byte-for-byte what approval will bind to (no generated_at drift).
    snap = snapshots.put(build_recommendation(policy, cp))
    return snap.model_copy(update={"status": store.status(snap.scenario_id)})


@app.get("/api/recommendation/{scenario_id}/audit", response_model=DecisionResponse)
def get_audit(scenario_id: str) -> DecisionResponse:
    decision = store.get(scenario_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"no decision recorded for {scenario_id}")
    return decision


@app.get("/api/audit/log", response_model=list[DecisionResponse])
def get_audit_log() -> list[DecisionResponse]:
    # the full durable, append-only decision ledger in commit order (Stage 4.4)
    return store.all_decisions()


@app.get("/api/audit/verify", response_model=AuditChainStatus)
def verify_audit_chain() -> AuditChainStatus:
    # tamper-evidence: recompute the hash chain over the persisted history
    return AuditChainStatus(**store.verify_chain())


@app.get("/api/marts")
def list_marts() -> dict:
    # Stage 4.5 — Looker-ready SQL views over the ledger; report name + row count
    return {"marts": {name: len(store.mart(name)) for name in MART_NAMES}}


@app.get("/api/marts/{name}")
def get_mart(name: str) -> list[dict]:
    if name not in MART_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown mart {name}; expected {MART_NAMES}")
    return store.mart(name)


@app.post("/api/recommendation/{scenario_id}/decision", response_model=DecisionResponse)
def decide(scenario_id: str, body: DecisionRequest) -> DecisionResponse:
    # approve/reject a STORED snapshot by id — never re-solve the optimizer
    rec = snapshots.get(scenario_id)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown or evicted scenario {scenario_id}; recalculate before deciding",
        )
    # IDEMPOTENT TERMINAL DECISION: a recorded decision is immutable. Replaying the
    # same action returns the stored decision (200); a conflicting action returns 409
    # — REGARDLESS of any later supersession or state drift. This must run BEFORE the
    # freshness guards, else re-confirming an already-approved plan would wrongly 409
    # once a newer scenario exists (the decision already happened; this is a no-op).
    if store.status(scenario_id) != "pending":
        try:
            return store.decide(rec, body.action, body.approver, body.notes)
        except DecisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    # STALE guard: the snapshot is only approvable while the engine/data/config
    # identity it was computed under still holds. If anything material changed
    # since, the displayed plan no longer matches reality — reject, don't execute.
    prov = engine_provenance()
    if (rec.data_fingerprint, rec.engine_version, rec.config_fingerprint,
            rec.calibration_fingerprint) != (
            prov["data_fingerprint"], prov["engine_version"],
            prov["config_fingerprint"], prov["calibration_fingerprint"]):
        raise HTTPException(
            status_code=409,
            detail=f"stale scenario {scenario_id}: engine/data/config/calibration changed "
                   "since it was computed; recalculate before deciding",
        )
    # SUPERSESSION: approving an older plan after a newer one was computed is a
    # likely mistake — only the most-recently-computed (active) plan is approvable.
    # Rejecting a superseded plan stays allowed (it never executes).
    if body.action == "approve" and not snapshots.is_latest(scenario_id):
        raise HTTPException(
            status_code=409,
            detail=f"superseded scenario {scenario_id}: a newer plan has been computed; "
                   "recalculate before approving",
        )
    # an infeasible plan must never be approved/executed (it can still be rejected)
    if body.action == "approve" and not rec.feasible:
        raise HTTPException(
            status_code=422,
            detail=f"scenario is infeasible and cannot be approved: {rec.conflicts}",
        )
    # a SENSITIVITY scenario uses calibration coefficients that are NOT in the
    # approved registry — it is a what-if for exploration only. It can never be
    # approved/executed (a formally approved calibration revision would instead be
    # written to the registry as a new version; that path is later). Reject is fine.
    if body.action == "approve" and rec.is_sensitivity_override:
        raise HTTPException(
            status_code=422,
            detail=f"sensitivity scenario {scenario_id} uses non-registry-approved "
                   "calibration overrides and cannot be approved; approve a registry-"
                   "approved plan or formalize the calibration revision first",
        )
    try:
        return store.decide(rec, body.action, body.approver, body.notes)
    except DecisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

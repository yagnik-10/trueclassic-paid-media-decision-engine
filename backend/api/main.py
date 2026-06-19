"""FastAPI app — the Stage 1 thin shell: recommendation + approve/reject + audit."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.api.recommendation import REC_ID, build_recommendation
from backend.api.schemas import DecisionRequest, DecisionResponse, Recommendation
from backend.api.store import DecisionConflict, DecisionStore

app = FastAPI(
    title="True Classic Paid Media Decision Engine — API",
    description="Stage 1 thin shell: one fixed recommendation + approve/reject audit.",
    version="0.1.0",
)

# The Next.js dev server runs on :3000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

store = DecisionStore()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": "1"}


@app.get("/api/recommendation", response_model=Recommendation)
def get_recommendation() -> Recommendation:
    rec = build_recommendation()
    # reflect the lifecycle state from the audit store so a refreshed page is correct
    rec.status = store.status(rec.rec_id)
    return rec


@app.get("/api/recommendation/{rec_id}/audit", response_model=DecisionResponse)
def get_audit(rec_id: str) -> DecisionResponse:
    decision = store.get(rec_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"no decision recorded for {rec_id}")
    return decision


@app.post("/api/recommendation/{rec_id}/decision", response_model=DecisionResponse)
def decide(rec_id: str, body: DecisionRequest) -> DecisionResponse:
    rec = build_recommendation()
    if rec_id != rec.rec_id or rec_id != REC_ID:
        raise HTTPException(status_code=404, detail=f"unknown recommendation {rec_id}")
    try:
        return store.decide(rec, body.action, body.approver, body.notes)
    except DecisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

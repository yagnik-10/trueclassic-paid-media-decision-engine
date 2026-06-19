"use client";

import { useEffect, useState } from "react";
import {
  type DecisionResponse,
  type Recommendation,
  getAudit,
  getRecommendation,
  postDecision,
} from "@/lib/api";

const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function deltaClass(pct: number) {
  if (pct > 0.05) return "up";
  if (pct < -0.05) return "down";
  return "flat";
}

export default function Page() {
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRecommendation()
      .then(async (r) => {
        setRec(r);
        // hydrate from the backend lifecycle so a refresh reflects a prior decision
        if (r.status !== "pending") {
          setDecision(await getAudit(r.rec_id));
        }
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  async function decide(action: "approve" | "reject") {
    if (!rec) return;
    setBusy(true);
    setError(null);
    try {
      setDecision(await postDecision(rec.rec_id, action, "marketer@trueclassic", undefined));
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !rec) {
    return (
      <div className="wrap">
        <h1>Paid Media Decision Engine</h1>
        <p className="err">Could not reach the API at the configured base URL. Is the backend running? ({error})</p>
      </div>
    );
  }
  if (!rec) return <div className="wrap"><p className="sub">Loading recommendation…</p></div>;

  const k = rec.kpis;
  const roasDelta = k.blended_roas_projected - k.blended_roas_current;

  return (
    <div className="wrap">
      <h1>Paid Media Decision Engine</h1>
      <p className="sub">
        Budget reallocation review · policy: <b>{rec.policy_mode}</b> ·{" "}
        {rec.is_fixed_placeholder && <span className="badge">Fixed placeholder — not yet optimizer-generated</span>}
      </p>

      <div className="kpis">
        <div className="kpi">
          <div className="label">Blended ROAS (current → projected)</div>
          <div className="value">{k.blended_roas_current.toFixed(2)}× → {k.blended_roas_projected.toFixed(2)}×</div>
          <div className={`delta ${roasDelta >= 0 ? "up" : "down"}`}>{roasDelta >= 0 ? "+" : ""}{roasDelta.toFixed(2)}×</div>
        </div>
        <div className="kpi">
          <div className="label">Current daily spend</div>
          <div className="value">{money(k.total_current_spend)}</div>
        </div>
        <div className="kpi">
          <div className="label">Recommended daily spend</div>
          <div className="value">{money(k.total_recommended_spend)}</div>
        </div>
        <div className="kpi">
          <div className="label">Held in reserve</div>
          <div className="value">{money(k.reserve)}</div>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Campaign</th>
            <th>Platform</th>
            <th className="num">Current</th>
            <th className="num">Recommended</th>
            <th className="num">Δ</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {rec.lines.map((ln) => (
            <tr key={ln.campaign_id}>
              <td>{ln.campaign_name}</td>
              <td>{ln.platform}</td>
              <td className="num">{money(ln.current_spend)}</td>
              <td className="num">{money(ln.recommended_spend)}</td>
              <td className={`num ${deltaClass(ln.delta_pct)}`}>{ln.delta_pct > 0 ? "+" : ""}{ln.delta_pct}%</td>
              <td>
                {ln.reason_codes.map((r) => <span key={r} className="chip">{r}</span>)}
                {ln.risk_flags.map((r) => <span key={r} className="chip risk">{r}</span>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="actions">
        <button className="approve" disabled={busy || !!decision} onClick={() => decide("approve")}>Approve</button>
        <button className="reject" disabled={busy || !!decision} onClick={() => decide("reject")}>Reject</button>
        {decision && <span className="sub">Decision recorded — approval is idempotent; a rejected plan cannot execute.</span>}
      </div>

      {error && <p className="err">{error}</p>}

      {decision && (
        <div className="audit">
          <h3>Audit · <span className={`status ${decision.status}`}>{decision.status.toUpperCase()}</span> by {decision.approver}</h3>
          <p className="mono">decided_at {decision.decided_at}{decision.idempotent_replay ? " · (idempotent replay)" : ""}</p>
          {decision.status === "approved" ? (
            <>
              <p className="sub">Stubbed execution payloads (no live writes):</p>
              {decision.execution_events.map((e) => (
                <p key={e.event_id} className="mono">
                  {e.platform} · {e.event_id} · {e.status} · hash {e.payload_hash.slice(0, 12)}…
                </p>
              ))}
            </>
          ) : (
            <p className="sub">No execution events — rejected recommendations never reach the (stubbed) platform adapters.</p>
          )}
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import Charts from "./Charts";
import {
  type ConstraintParams,
  type DecisionResponse,
  type Recommendation,
  getAudit,
  getRecommendation,
  postDecision,
} from "@/lib/api";

type Policy = "expected" | "conservative";

const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function deltaClass(pct: number) {
  if (pct > 0.05) return "up";
  if (pct < -0.05) return "down";
  return "flat";
}

const DEFAULTS: ConstraintParams = {
  roas_floor: 4.0, nc_cpa_target: 45, prospecting_min_share: 0.33, movement_bound: 0.2,
  reserve_mode: "growth", calibration_overrides: {},
};

const SEGMENT_LABEL: Record<string, string> = {
  meta_prospecting: "Meta prospecting",
  meta_retargeting: "Meta retargeting",
  google_brand: "Google brand",
  google_nonbrand: "Google nonbrand",
};

const PACING_LABEL: Record<string, string> = {
  scale_opportunity: "leaving revenue on the table",
  capped_constrained: "capped \u2014 inventory-limited",
  strategic_floor: "retained for prospecting floor",
  pullback_candidate: "underperforming \u2014 reducing",
  waste_risk: "burning full budget",
  healthy: "healthy headroom",
};

function Field({ label, value, step, min, max, suffix, percent, disabled, onChange }: {
  label: string; value: number; step: number; min: number; max: number;
  suffix?: string; percent?: boolean; disabled?: boolean; onChange: (v: number) => void;
}) {
  // a 'percent' field shows a fraction as a whole-number percentage (0.20 → 20%)
  // and converts back on change, so the UI never exposes raw fractions.
  const shown = percent ? Math.round(value * 1000) / 10 : value;
  const handle = (raw: number) => onChange(percent ? raw / 100 : raw);
  return (
    <label className="cfield">
      <span>{label}</span>
      <span className="cinput">
        <input type="number" value={shown} step={step} min={min} max={max} disabled={disabled}
               onChange={(e) => handle(Number(e.target.value))} />
        {(percent ? "%" : suffix) && <em>{percent ? "%" : suffix}</em>}
      </span>
    </label>
  );
}

export default function Page() {
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [solving, setSolving] = useState(false);
  const [policy, setPolicy] = useState<Policy>("expected");
  const [cons, setCons] = useState<ConstraintParams>(DEFAULTS);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const decided = !!decision;

  // Seed the form from the BACKEND's own defaults (no constraints sent), so the
  // UI never hard-codes policy values that could drift from config.py.
  async function loadDefaults() {
    setPolicy("expected");
    const r = await getRecommendation("expected");
    setRec(r);
    setCons(r.constraints);
    if (r.status !== "pending") setDecision(await getAudit(r.scenario_id));
  }

  useEffect(() => {
    loadDefaults().catch((e) => setError(String(e.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function reload(p: Policy, c: ConstraintParams) {
    if (timer.current) clearTimeout(timer.current);
    setSolving(true);
    timer.current = setTimeout(async () => {
      try {
        setRec(await getRecommendation(p, c));
        setError(null);
      } catch (e: any) {
        setError(String(e.message ?? e));
      } finally {
        setSolving(false);
      }
    }, 250);
  }

  function update(patch: Partial<ConstraintParams>) {
    const next = { ...cons, ...patch };
    setCons(next);
    reload(policy, next);
  }
  function setPol(p: Policy) {
    setPolicy(p);
    reload(p, cons);
  }
  function reset() {
    setError(null);
    loadDefaults().catch((e) => setError(String(e.message ?? e)));
  }

  async function decide(action: "approve" | "reject") {
    if (!rec) return;
    setBusy(true); setError(null);
    try {
      // bind to the displayed snapshot by scenario_id — no re-solve
      setDecision(await postDecision(rec.scenario_id, action, "marketer@trueclassic", undefined));
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !rec) {
    return <div className="wrap"><h1>Paid Media Decision Engine</h1>
      <p className="err">Could not reach the API. Is the backend running? ({error})</p></div>;
  }
  if (!rec) return <div className="wrap"><p className="sub">Loading recommendation…</p></div>;

  const k = rec.kpis;
  const roasDelta = k.blended_roas_projected - k.blended_roas_current;
  const cmDelta = k.cm_roas_projected - k.cm_roas_current;
  const netDelta = k.net_contribution_projected - k.net_contribution_current;
  // the displayed plan is "dirty" while re-solving or when the inputs no longer
  // match what's shown — approval is disabled until the exact plan is recomputed
  const dirty = solving || policy !== rec.policy_mode ||
    JSON.stringify(cons) !== JSON.stringify(rec.constraints);

  return (
    <div className="wrap">
      <h1>Paid Media Decision Engine</h1>
      <p className="sub">
        Budget reallocation ·{" "}
        <span className="badge" style={{ color: rec.feasible ? "var(--green)" : "var(--red)", borderColor: rec.feasible ? "rgba(56,193,114,.4)" : "rgba(227,85,79,.4)", background: rec.feasible ? "rgba(56,193,114,.08)" : "rgba(227,85,79,.08)" }}>
          SLSQP optimizer · {rec.feasible ? "feasible" : "infeasible"}
        </span>
        {rec.is_sensitivity_override && (
          <span className="badge" style={{ color: "var(--amber)", borderColor: "rgba(224,169,59,.5)", background: "rgba(224,169,59,.1)" }}>
            Sensitivity scenario · not registry-approved
          </span>
        )}
        {solving && <span className="sub"> · solving…</span>}
      </p>

      <div className="controls">
        <div className="cgroup">
          <span className="clabel">Risk policy</span>
          <div className="toggle">
            <button className={policy === "expected" ? "on" : ""} disabled={decided} onClick={() => setPol("expected")}>Expected</button>
            <button className={policy === "conservative" ? "on" : ""} disabled={decided} onClick={() => setPol("conservative")}>Conservative</button>
          </div>
        </div>
        <div className="cgroup">
          <span className="clabel">Budget mode</span>
          <div className="toggle">
            <button className={cons.reserve_mode === "growth" ? "on" : ""} disabled={decided}
                    title="Deploy the full budget across eligible campaigns"
                    onClick={() => update({ reserve_mode: "growth" })}>Growth</button>
            <button className={cons.reserve_mode === "efficiency_first" ? "on" : ""} disabled={decided}
                    title="Hold budget in reserve when the next dollar can't clear its hurdle"
                    onClick={() => update({ reserve_mode: "efficiency_first" })}>Efficiency-first</button>
          </div>
        </div>
        <Field label="ROAS floor" value={cons.roas_floor} step={0.1} min={2} max={8} suffix="×" disabled={decided} onChange={(v) => update({ roas_floor: v })} />
        <Field label="NC-CPA target" value={cons.nc_cpa_target} step={1} min={10} max={120} suffix="$" disabled={decided} onChange={(v) => update({ nc_cpa_target: v })} />
        <Field label="Prospecting min" value={cons.prospecting_min_share} percent step={1} min={10} max={60} disabled={decided} onChange={(v) => update({ prospecting_min_share: v })} />
        <Field label="Movement bound" value={cons.movement_bound} percent step={1} min={5} max={40} disabled={decided} onChange={(v) => update({ movement_bound: v })} />
        <button className="small" disabled={decided} onClick={reset}>Reset</button>
        <button className="small preset" disabled={decided}
                title="Demo: ROAS floor 4.1 in efficiency-first. Growth turns infeasible; efficiency-first holds budget in reserve to protect the floor."
                onClick={() => update({ roas_floor: 4.1, reserve_mode: "efficiency_first" })}>
          Efficiency stress (4.1×)
        </button>
        {policy === "conservative" && (
          <span className="clabel">effective movement ±{(rec.effective_movement_bound * 100).toFixed(0)}% (Conservative trims to 75%)</span>
        )}
      </div>

      {!rec.feasible && rec.conflicts.length > 0 && (
        <div className="conflict">
          <b>Infeasible under these constraints.</b> The allocation below is a{" "}
          <em>diagnostic candidate</em> (the clipped solver iterate) — not a proven
          closest-feasible plan, and it cannot be approved. Unmet constraints (exact shortfalls):
          <ul>{rec.conflicts.map((c) => <li key={c}>{c}</li>)}</ul>
          Loosen a constraint to make it feasible.
        </div>
      )}

      <div className="kpis">
        <div className="kpi primary">
          <div className="label">CM ROAS (contribution per ad $ · breaks even at 1.0×)</div>
          <div className="value">{k.cm_roas_current.toFixed(2)}× → {k.cm_roas_projected.toFixed(2)}×</div>
          <div className={`delta ${cmDelta >= 0 ? "up" : "down"}`}>{cmDelta >= 0 ? "+" : ""}{cmDelta.toFixed(2)}× · primary success metric</div>
        </div>
        <div className="kpi primary">
          <div className="label">Net contribution / day (after ad spend)</div>
          <div className="value">{money(k.net_contribution_current)} → {money(k.net_contribution_projected)}</div>
          <div className={`delta ${netDelta >= 0 ? "up" : "down"}`}>{netDelta >= 0 ? "+" : ""}{money(netDelta)}/day{k.net_contribution_current > 0 ? ` (${netDelta >= 0 ? "+" : ""}${((netDelta / k.net_contribution_current) * 100).toFixed(1)}%)` : ""}</div>
        </div>
        <div className="kpi">
          <div className="label">Calibrated ROAS (incremental · enforced floor {cons.roas_floor.toFixed(1)}×)</div>
          <div className="value">{k.blended_roas_current.toFixed(2)}× → {k.blended_roas_projected.toFixed(2)}×</div>
          <div className={`delta ${roasDelta >= 0 ? "up" : "down"}`}>{roasDelta >= 0 ? "+" : ""}{roasDelta.toFixed(2)}× · governance floor</div>
        </div>
        <div className="kpi">
          <div className="label">Daily spend (current → recommended)</div>
          <div className="value">{money(k.total_current_spend)} → {money(k.total_recommended_spend)}</div>
          <div className="delta flat">equal-or-lower spend</div>
        </div>
        <div className="kpi">
          <div className="label">Reported ROAS (platform-reported · context)</div>
          <div className="value">{k.reported_roas_current.toFixed(2)}× → {k.reported_roas_projected.toFixed(2)}×</div>
          <div className="delta flat">over-attribution gap</div>
        </div>
        <div className="kpi">
          <div className="label">Held in reserve ({cons.reserve_mode === "efficiency_first" ? "efficiency-first" : "growth"})</div>
          <div className="value">{money(k.reserve)}</div>
          <div className={`delta ${k.reserve > 0 ? "up" : "flat"}`}>
            {k.total_current_spend > 0 ? ((k.reserve / k.total_current_spend) * 100).toFixed(1) : "0.0"}% of current ·{" "}
            {cons.reserve_mode === "efficiency_first" ? "withheld below hurdle" : "full deployment"}
          </div>
        </div>
      </div>

      <div className="calibration">
        <h3 style={{ margin: "28px 0 4px" }}>Platform vs calibrated sensitivity</h3>
        <p className="sub" style={{ marginTop: 0 }}>
          The optimizer decides on <em>calibrated</em> (incremental) revenue. Platform-reported
          ROAS is context — the over-attribution gap. Perturb a segment coefficient to see how
          the recommendation responds when the approved calibration source changes.
        </p>
        {rec.is_sensitivity_override && (
          <div className="conflict" style={{ borderColor: "rgba(224,169,59,.5)", background: "rgba(224,169,59,.08)" }}>
            <b>Sensitivity scenario — not registry-approved.</b> Forecast and response models were
            re-estimated under alternate calibration coefficients (the historical calibrated revenue
            series is recomputed, not just the headline KPI). This is a what-if for exploration and
            <b> cannot be approved</b>; reset the sliders or formalize the calibration revision first.
          </div>
        )}
        <table className="cal-table">
          <thead>
            <tr>
              <th>Campaign</th>
              <th className="num">Platform ROAS</th>
              <th className="num">Calibrated ROAS</th>
              <th className="num">Coeff.</th>
              <th>Gap</th>
            </tr>
          </thead>
          <tbody>
            {rec.lines.map((ln) => {
              const gap = ln.platform_roas_current - ln.calibrated_roas_current;
              return (
                <tr key={ln.campaign_id}>
                  <td>
                    {ln.campaign_name}
                    <div className="mono" style={{ fontSize: 11 }}>{ln.platform}</div>
                  </td>
                  <td className="num plat">{ln.platform_roas_current.toFixed(2)}×</td>
                  <td className="num cal">{ln.calibrated_roas_current.toFixed(2)}×</td>
                  <td className="num mono">{ln.incrementality.toFixed(2)}</td>
                  <td className={`num ${gap > 1 ? "over" : "flat"}`}>
                    {gap >= 0 ? "+" : ""}{gap.toFixed(2)}×
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {rec.calibration_registry.length > 0 && (
          <div className="cal-prov">
            <div className="cal-prov-title">Calibration registry (provenance)</div>
            <ul className="prov-list">
              {rec.calibration_registry.map((row) => (
                <li key={row.registry_id} className={row.overridden ? "overridden" : ""}>
                  <b>{SEGMENT_LABEL[row.segment] ?? row.segment}</b>
                  <span className="mono">
                    {row.coefficient.toFixed(2)}
                    {row.overridden && ` (approved ${row.approved_coefficient.toFixed(2)})`}
                  </span>
                  <span className="chip">{row.source.replace(/_/g, " ")}</span>
                  <span className="chip">{row.confidence} confidence</span>
                  <span className="mono muted">
                    {row.effective_start}{row.effective_end ? ` → ${row.effective_end}` : " → open"}
                    {row.is_synthetic ? " · synthetic" : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!decided && rec.calibration_registry.length > 0 && (
          <div className="cal-sens">
            <div className="cal-prov-title">Sensitivity — perturb segment coefficients</div>
            {rec.calibration_registry.map((row) => {
              const approved = row.approved_coefficient;
              const current = cons.calibration_overrides[row.segment] ?? approved;
              const isOverride = row.segment in cons.calibration_overrides;
              return (
                <label key={row.segment} className="sens-row">
                  <span>{SEGMENT_LABEL[row.segment] ?? row.segment}</span>
                  <input type="range" min={0.1} max={1} step={0.05} value={current}
                         disabled={decided}
                         onChange={(e) => {
                           const v = Number(e.target.value);
                           const next = { ...cons.calibration_overrides };
                           if (Math.abs(v - approved) < 0.001) delete next[row.segment];
                           else next[row.segment] = v;
                           update({ calibration_overrides: next });
                         }} />
                  <span className="mono">{current.toFixed(2)}</span>
                  {isOverride && (
                    <button type="button" className="small" onClick={() => {
                      const next = { ...cons.calibration_overrides };
                      delete next[row.segment];
                      update({ calibration_overrides: next });
                    }}>reset</button>
                  )}
                </label>
              );
            })}
          </div>
        )}
      </div>

      <table>
        <thead>
          <tr>
            <th>Campaign</th>
            <th className="num">Current</th>
            <th className="num">Recommended</th>
            <th className="num">Δ</th>
            <th className="num">Marginal ROAS</th>
            <th className="num">7-day P50</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {rec.lines.map((ln) => (
            <tr key={ln.campaign_id}>
              <td>{ln.campaign_name}<div className="mono" style={{ fontSize: 11 }}>{ln.platform}</div></td>
              <td className="num">{money(ln.current_spend)}</td>
              <td className="num">{money(ln.recommended_spend)}</td>
              <td className={`num ${deltaClass(ln.delta_pct)}`}>{ln.delta_pct > 0 ? "+" : ""}{ln.delta_pct}%</td>
              <td className="num">{ln.marginal_roas.toFixed(2)}×</td>
              <td className="num" title={ln.forecast_model}>{money(ln.forecast_p50)}</td>
              <td>
                {ln.reason_codes.map((r) => <span key={r} className="chip">{r}</span>)}
                {ln.risk_flags.map((r) => <span key={r} className="chip risk">{r}</span>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sub" style={{ margin: "8px 0 0", fontSize: 11 }}>
        Revenue level is anchored on the selected BAU forecast (7-day P50 ÷ horizon, per campaign);
        the optimizer adds only the spend-change response delta on top.
      </p>

      <div className="pacing">
        <h3 style={{ margin: "28px 0 4px" }}>Pacing &amp; budget utilization</h3>
        <p className="sub" style={{ marginTop: 0 }}>
          Spend vs daily cap. A campaign near its cap and above its hurdle is an efficient winner
          <em> leaving revenue on the table</em>; near its cap and below the hurdle it is
          <em> burning its full budget</em>.
        </p>
        <ul className="util">
          {[...rec.lines].sort((a, b) => b.current_utilization - a.current_utilization).map((ln) => {
            const cur = Math.min(1, ln.current_utilization);
            const recU = Math.min(1, ln.recommended_utilization);
            return (
              <li key={ln.campaign_id} className={`utilrow ${ln.pacing_flag}`}>
                <div className="utilhead">
                  <span className="utilname">{ln.campaign_name}</span>
                  {ln.pacing_flag !== "healthy" && (
                    <span className={`chip pace ${ln.pacing_flag}`}>{PACING_LABEL[ln.pacing_flag]}</span>
                  )}
                  <span className="utilpct mono">{Math.round(ln.current_utilization * 100)}% → {Math.round(ln.recommended_utilization * 100)}% of cap</span>
                </div>
                <div className="utilbar" title={`cap ${money(ln.daily_cap)}/day`}>
                  <span className="utilfill cur" style={{ width: `${cur * 100}%` }} />
                  <span className="utilmark rec" style={{ left: `${recU * 100}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {rec.binding && (rec.binding.portfolio.length > 0 || rec.binding.per_campaign.length > 0) && (
        <div className="binding">
          <h3 style={{ margin: "28px 0 8px" }}>Why this plan</h3>
          <p className="sub" style={{ marginTop: 0 }}>
            Which business constraints are binding vs. slack, and the hard bound that pins each moved campaign.
          </p>
          <div className="bindrow">
            {rec.binding.portfolio.map((b) => (
              <span key={b.name} className={`badge bstat ${b.status}`} title={b.detail}>
                {b.name.replace(/_/g, " ")} · {b.status}
                <em className="bdetail">{b.detail}</em>
              </span>
            ))}
          </div>
          {rec.binding.solver && (
            <>
              <p className="sub" style={{ marginTop: 6, fontSize: 11 }}>
                Solver: SLSQP {rec.binding.solver.local_optimality_converged ? "solver-converged recommendation" : "feasible improving candidate — solver convergence not achieved"} in{" "}
                {rec.binding.solver.iterations} iterations
                {typeof rec.binding.solver.n_feasible_starts === "number"
                  ? ` · ${rec.binding.solver.n_feasible_starts}/${rec.binding.solver.n_starts} feasible starts`
                  : ""}
                {rec.binding.solver.message ? ` — ${rec.binding.solver.message}` : ""}
              </p>
              {rec.binding.solver.warning && (
                <p className="sub" style={{ marginTop: 4, fontSize: 11, color: "var(--amber)" }}>
                  ⚠ {rec.binding.solver.warning}
                </p>
              )}
            </>
          )}
          {rec.binding.per_campaign.length > 0 && (
            <ul className="bounds">
              {rec.binding.per_campaign.map((c) => {
                const name = rec.lines.find((l) => l.campaign_id === c.campaign_id)?.campaign_name
                  ?? c.campaign_id;
                return (
                  <li key={c.campaign_id}>
                    <b>{name}</b>{" "}
                    {c.limits.map((lim) => <span key={lim} className="chip">{lim.replace(/_/g, " ")}</span>)}
                    <span className="mono" style={{ fontSize: 11, marginLeft: 6 }}>{c.detail}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      <h3 style={{ margin: "28px 0 4px" }}>Analysis</h3>
      <Charts rec={rec} />

      <div className="actions">
        <button className="approve" disabled={busy || decided || !rec.feasible || dirty || rec.is_sensitivity_override} onClick={() => decide("approve")}>Approve</button>
        <button className="reject" disabled={busy || decided || dirty} onClick={() => decide("reject")}>Reject</button>
        {solving && !decided && <span className="sub">Recomputing — decide once the plan settles.</span>}
        {!solving && dirty && !decided && !error && <span className="sub">Inputs changed — recompute to decide.</span>}
        {!dirty && !rec.feasible && !decided && <span className="sub">Approve is disabled while the plan is infeasible.</span>}
        {!dirty && rec.feasible && rec.is_sensitivity_override && !decided && <span className="sub">Approve is disabled for sensitivity scenarios (non-registry-approved calibration).</span>}
        {decided && <span className="sub">Decision recorded for scenario <span className="mono">{rec.scenario_id}</span> — approval is idempotent; a rejected plan cannot execute.</span>}
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
                <p key={e.event_id} className="mono">{e.platform} · {e.event_id} · {e.status} · hash {e.payload_hash.slice(0, 12)}…</p>
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

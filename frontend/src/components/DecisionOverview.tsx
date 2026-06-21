import { useEffect, useState } from 'react';
import { Info, AlertTriangle, AlertOctagon, Check, Loader2, Ban, Sparkles } from 'lucide-react';
import { ActiveTab } from '../types';
import { useRecommendation } from '../state/RecommendationContext';
import type { CampaignLine, Narration } from '../lib/api';
import { getNarration } from '../lib/api';
import ExecutionPanel from './ExecutionPanel';
import { PlatformLogo } from './BrandLogo';

interface DecisionOverviewProps {
  onNavigateToTab: (tab: ActiveTab) => void;
}

const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

// strip the "Google — " / "Meta — " platform prefix — the logo already conveys it
const shortCampaign = (n: string) => n.replace(/^(Google|Meta)\s*[—–-]\s*/, '');

// Group live campaign lines into the two allocation views — Meta + Google only.
function groupBy(lines: CampaignLine[], mode: 'channel' | 'objective') {
  const buckets = new Map<string, { key: string; platform: string; name: string; current: number; recommended: number; cap: number }>();
  for (const ln of lines) {
    let key: string;
    let name: string;
    if (mode === 'channel') {
      key = ln.platform;
      name = ln.platform === 'meta' ? 'Meta Ads' : ln.platform === 'google' ? 'Google Ads' : ln.platform;
    } else {
      const seg = ln.segment.toLowerCase();
      const prospecting = seg.includes('prospect') || seg.includes('nonbrand') || seg.includes('non_brand');
      key = prospecting ? 'acq' : 'ret';
      name = prospecting ? 'Prospecting / Acquisition' : 'Retargeting / Brand';
    }
    const b = buckets.get(key) ?? { key, platform: ln.platform, name, current: 0, recommended: 0, cap: 0 };
    b.current += ln.current_spend;
    b.recommended += ln.recommended_spend;
    b.cap += ln.daily_cap;
    buckets.set(key, b);
  }
  return [...buckets.values()];
}

function AllocationBars({ lines, mode }: { lines: CampaignLine[]; mode: 'channel' | 'objective' }) {
  const items = groupBy(lines, mode);
  const max = Math.max(...items.map((i) => Math.max(i.current, i.recommended, i.cap)), 1) * 1.05;
  return (
    <div className="space-y-6 animate-fade-in">
      {items.map((item) => {
        const curPct = (item.current / max) * 100;
        const recPct = (item.recommended / max) * 100;
        const capPct = (item.cap / max) * 100;
        const diff = item.recommended - item.current;
        const shrink = item.recommended < item.current;
        return (
          <div key={item.name} className="space-y-3">
            <div className="flex justify-between items-center font-sans">
              <div className="flex items-center gap-2">
                {mode === 'channel' && <PlatformLogo platform={item.platform} className="w-4 h-4 shrink-0" />}
                <span className="text-sm font-semibold text-slate-800 tracking-tight">{item.name}</span>
              </div>
              <div className="flex items-center text-xs sm:text-sm font-medium">
                <span className="text-slate-400 font-data-mono text-[13px]">{money(item.current)}</span>
                <span className="text-slate-300 mx-2 text-[12px]">→</span>
                <span className="text-[#0f172a] font-bold font-data-mono text-[13px]">{money(item.recommended)}</span>
                <span className={`font-data-mono font-bold text-[13px] ml-3 ${diff >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                  {diff >= 0 ? '+' : '-'}{money(Math.abs(diff))}
                </span>
              </div>
            </div>
            <div className="relative w-full bg-slate-50 h-5 rounded-md overflow-hidden flex items-center border border-slate-100">
              {shrink ? (
                <>
                  <div style={{ width: `${recPct}%` }} className="h-full bg-slate-300 transition-all duration-300" />
                  <div style={{ width: `${curPct - recPct}%` }} className="h-full bg-rose-200 transition-all duration-300" />
                </>
              ) : (
                <>
                  <div style={{ width: `${curPct}%` }} className="h-full bg-slate-300 transition-all duration-300" />
                  <div style={{ width: `${recPct - curPct}%` }} className="h-full bg-emerald-500 transition-all duration-300" />
                </>
              )}
              <div style={{ left: `${capPct}%` }} className="absolute inset-y-0 w-0 border-r-2 border-dashed border-slate-400/70 z-10 pointer-events-none" />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Per-campaign budget movement: a $0-centered diverging bar. Bar LENGTH = dollars
// moved per day on a shared scale; green = scale up, red = pull back; inventory-held
// campaigns are shown flat. This is the clearest read of the reallocation decision.
function MovementBars({ lines }: { lines: CampaignLine[] }) {
  const rows = lines
    .map((l) => ({ ...l, move: Math.round(l.recommended_spend - l.current_spend) }))
    .sort((a, b) => b.move - a.move); // scale-ups on top, pull-backs at the bottom
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.move)), 1);
  return (
    <div className="space-y-4 animate-fade-in">
      {rows.map((r) => {
        const held = r.move === 0; // inventory-held / no-change campaigns round to $0/day
        const up = r.move > 0;
        const pct = (Math.abs(r.move) / maxAbs) * 46; // max move fills ~half the track
        return (
          <div key={r.campaign_id} className="grid grid-cols-12 gap-3 items-center font-sans">
            <div className="col-span-4 flex items-center gap-2 min-w-0 pr-1" title={r.campaign_name}>
              <PlatformLogo platform={r.platform} className="w-4 h-4 shrink-0" />
              <span className="text-xs font-semibold text-slate-700 truncate tracking-tight">{shortCampaign(r.campaign_name)}</span>
            </div>
            <div className="col-span-6 relative bg-slate-50 h-5 rounded-md border border-slate-100 flex items-center overflow-hidden">
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-slate-200 z-10 pointer-events-none" />
              {up && (
                <div className="absolute h-full bg-emerald-500 rounded-r transition-all duration-300" style={{ left: '50%', width: `${pct}%` }} />
              )}
              {r.move < 0 && (
                <div className="absolute h-full bg-rose-500 rounded-l transition-all duration-300" style={{ left: `${50 - pct}%`, width: `${pct}%` }} />
              )}
            </div>
            <div className="col-span-2 text-right">
              {held ? (
                <span className="inline-flex items-center px-2 py-0.5 rounded bg-slate-50 text-slate-400 font-data-mono text-[10px] font-bold border border-slate-100 uppercase tracking-wider">
                  held
                </span>
              ) : (
                <span className={`font-data-mono font-bold text-xs sm:text-[13px] ${up ? 'text-emerald-600' : 'text-rose-600'}`}>
                  {up ? '+' : '-'}{money(Math.abs(r.move))}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// A policy-guardrail tile: the actual-vs-threshold detail straight from the solver's
// binding report, with a pass/binding/violated chip. 'binding' = satisfied but at the
// margin (a meaningful "why this plan" signal); 'violated' only on an infeasible plan.
function Guardrail({ label, detail, status }: { label: string; detail: string; status: string }) {
  const violated = status === 'violated';
  const binding = status === 'binding';
  const chip = violated
    ? { txt: 'Violated', cls: 'bg-red-50 text-red-800 border-red-200' }
    : binding
    ? { txt: 'Binding', cls: 'bg-amber-50 text-amber-800 border-amber-200' }
    : { txt: 'Within', cls: 'bg-green-50 text-green-800 border-green-200' };
  return (
    <div className={`bg-white border rounded-xl p-4 shadow-sm transition-all ${violated ? 'border-red-200' : 'border-[#e2e8f0] hover:border-[#00714d]/40'}`}>
      <div className="flex justify-between items-center gap-2 mb-2">
        <span className="text-[#45464d] text-xs font-semibold uppercase tracking-wider">{label}</span>
        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border shrink-0 ${chip.cls}`}>
          {chip.txt}
        </span>
      </div>
      <div className="text-[13px] font-bold font-data-mono text-[#0d1c2d] leading-snug">{detail}</div>
    </div>
  );
}

// A large headline metric card: greyed current → bold recommended, with a green pill.
function BigMetric({ label, info, current, recommended, pill }: {
  label: string; info: string; current: string; recommended: string; pill: string;
}) {
  return (
    <div className="bg-white border border-[#cbd5e1]/50 rounded-xl p-5 shadow-sm hover:shadow-md transition-all relative">
      <div className="flex justify-between items-start">
        <span className="text-xs font-bold text-[#475569] tracking-wider uppercase">{label}</span>
        <span title={info} className="cursor-help"><Info size={14} className="text-[#94a3b8] hover:text-[#475569] transition-colors" /></span>
      </div>
      <div className="mt-3 flex items-baseline flex-wrap">
        <span className="text-3xl font-bold font-headline-lg text-slate-400 mr-2">{current}</span>
        <span className="text-xl font-normal text-slate-400 mx-1">→</span>
        <span className="text-3xl font-extrabold font-headline-lg text-[#0f172a] ml-1">{recommended}</span>
      </div>
      <div className="mt-2.5">
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-[#f0fdf4] text-[#006c49] font-data-mono text-xs font-semibold border border-[#dcfce7]">
          {pill}
        </span>
      </div>
    </div>
  );
}

// A compact context card: greyed current → bold recommended (or a single value) + caption.
function ContextCard({ label, current, recommended, sub }: {
  label: string; current?: string; recommended: string; sub: string;
}) {
  return (
    <div className="bg-white border border-[#cbd5e1]/45 rounded-xl p-4 shadow-sm relative">
      <span className="text-[10px] font-bold text-[#475569] tracking-wider uppercase block mb-1">{label}</span>
      <div className="text-sm font-semibold font-data-mono mt-2">
        {current && <><span className="text-slate-400">{current}</span> <span className="text-slate-400 font-normal">→</span> </>}
        <span className="text-[#0f172a] font-bold">{recommended}</span>
      </div>
      <div className="text-[10px] text-[#475569] font-data-mono mt-1 font-medium">{sub}</div>
    </div>
  );
}

// Section header for a scorecard group, with an optional dimmed descriptor.
function GroupLabel({ title, desc }: { title: string; desc?: string }) {
  return (
    <div className="text-[10px] sm:text-xs font-bold text-[#64748b] tracking-wider uppercase">
      {title}{desc && <span className="font-normal text-slate-400"> — {desc}</span>}
    </div>
  );
}

export default function DecisionOverview({ onNavigateToTab }: DecisionOverviewProps) {
  const { rec, decision, loading, solving, error, decided, busy, dirty, approveBlockedReason, decide } =
    useRecommendation();
  const [mode, setMode] = useState<'movement' | 'channel' | 'objective'>('movement');

  // Stage 5 bounded narrator: fetch a prose explanation for the active snapshot. The
  // numbers below always render from app state; this only replaces the summary prose.
  // Re-fetches whenever the scenario (constraints) changes; degrades silently.
  const [narration, setNarration] = useState<Narration | null>(null);
  const [narrationLoading, setNarrationLoading] = useState(false);
  const scenarioId = rec?.scenario_id;
  useEffect(() => {
    if (!scenarioId) {
      setNarration(null);
      setNarrationLoading(false);
      return;
    }
    let cancelled = false;
    setNarration(null);
    setNarrationLoading(true);
    getNarration(scenarioId)
      .then((n) => !cancelled && setNarration(n))
      .catch(() => !cancelled && setNarration(null))
      .finally(() => !cancelled && setNarrationLoading(false));
    return () => {
      cancelled = true;
    };
  }, [scenarioId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[#45464d] text-sm animate-fade-in">
        <Loader2 size={16} className="animate-spin text-[#00714d]" /> Loading recommendation from the engine…
      </div>
    );
  }
  if (error && !rec) {
    return (
      <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm animate-fade-in">
        <b>Could not reach the decision API.</b> Is the backend running on <code>:8000</code>? ({error})
      </div>
    );
  }
  if (!rec) return null;

  const k = rec.kpis;
  const cmDelta = k.cm_roas_projected - k.cm_roas_current;
  const netDelta = k.net_contribution_projected - k.net_contribution_current;
  const netPct = k.net_contribution_current > 0 ? (netDelta / k.net_contribution_current) * 100 : 0;
  const approved = decision?.status === 'approved';
  const rejected = decision?.status === 'rejected';

  // Honest, data-derived recommendation summary (no hardcoded narration).
  const ups = rec.lines.filter((l) => l.delta_pct > 0.5).sort((a, b) => b.delta_pct - a.delta_pct);
  const downs = rec.lines.filter((l) => l.delta_pct < -0.5).sort((a, b) => a.delta_pct - b.delta_pct);
  const summaryParts: string[] = [];
  if (ups.length) summaryParts.push(`scale ${ups.slice(0, 2).map((l) => l.campaign_name).join(', ')}`);
  if (downs.length) summaryParts.push(`trim ${downs.slice(0, 2).map((l) => l.campaign_name).join(', ')}`);
  summaryParts.push(k.reserve > 0 ? `hold ${money(k.reserve)}/day in reserve` : 'deploy the full budget');
  const summary = summaryParts.join('; ') + '.';

  // Binding constraints + line risk flags, straight from the solver.
  const portfolio = rec.binding?.portfolio ?? [];
  const binding = portfolio.filter((b) => b.status === 'binding' || b.status === 'violated');
  const riskLines = rec.lines.filter((l) => l.risk_flags.length > 0);

  // Guardrail tiles read the solver's own actual-vs-threshold detail (fallback to the
  // KPIs if a binding row is absent), so the scorecard never re-derives the numbers.
  const byName = (n: string) => portfolio.find((b) => b.name === n);
  const roasG = byName('blended_roas_floor');
  const cpaG = byName('nc_cpa_target');
  const prospG = byName('prospecting_min_share');
  const roasDetail = roasG?.detail ?? `${k.blended_roas_projected.toFixed(2)}× vs floor ${rec.constraints.roas_floor.toFixed(2)}×`;
  const cpaDetail = cpaG?.detail ?? `$${k.nc_cpa_projected.toFixed(2)} vs target ${money(rec.constraints.nc_cpa_target)}`;
  const prospDetail = prospG?.detail ?? `min ${(rec.constraints.prospecting_min_share * 100).toFixed(0)}%`;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header & status */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
          <h2 className="text-2xl font-bold font-headline-lg text-[#0d1c2d] tracking-tight">Executive Summary</h2>
          <p className="text-sm text-[#45464d] mt-1">
            Optimized Meta + Google allocation on contribution margin. Scenario{' '}
            <span className="font-data-mono text-xs">{rec.scenario_id.slice(0, 12)}…</span> · policy {rec.policy_mode}.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold border ${rec.feasible ? 'bg-[#d1fae5] text-[#006c49] border-[#6cf8bb]/40' : 'bg-[#fee2e2] text-[#7f1d1d] border-[#fca5a5]'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${rec.feasible ? 'bg-[#006c49]' : 'bg-[#7f1d1d]'}`}></span>
            SLSQP · {rec.feasible ? 'feasible' : 'infeasible'}
          </span>
          {rec.is_sensitivity_override && (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-[#fef3c7] text-[#78350f] text-xs font-semibold border border-[#fcd34d]/50">
              Sensitivity · not registry-approved
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-[#f1f5f9] text-[#0f172a] text-xs font-semibold border border-[#c6c6cd]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#0f172a]"></span>
            {approved ? 'Approved · recorded to ledger' : rejected ? 'Rejected' : 'Human approval required'}
          </span>
          {solving && (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-white text-[#45464d] text-xs font-semibold border border-[#c6c6cd]">
              <Loader2 size={11} className="animate-spin text-[#00714d]" /> solving…
            </span>
          )}
        </div>
      </div>

      {/* Infeasible banner — diagnostic candidate, not approvable */}
      {!rec.feasible && rec.conflicts.length > 0 && (
        <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm">
          <b>Infeasible under these constraints.</b> The allocation below is a diagnostic candidate, not a
          proven closest-feasible plan, and cannot be approved. Unmet constraints:
          <ul className="list-disc ml-5 mt-1">{rec.conflicts.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
      )}

      {/* Success-criteria scorecard — template-styled groups (primary → economics → guardrails → context) */}
      <div className="space-y-5">
        {/* Group 1 — required KPI + the objective maximized under it */}
        <div className="space-y-3">
          <GroupLabel title="Primary success metric & outcome" desc="the required KPI and the objective maximized under it" />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <BigMetric label="Calibrated Blended ROAS"
              info="The brief's required success metric — calibrated blended ROAS vs the required floor"
              current={`${k.blended_roas_current.toFixed(2)}×`} recommended={`${k.blended_roas_projected.toFixed(2)}×`}
              pill={k.blended_roas_projected >= rec.constraints.roas_floor
                ? `clears ${rec.constraints.roas_floor.toFixed(1)}× required floor (+${(k.blended_roas_projected - rec.constraints.roas_floor).toFixed(2)}×)`
                : `below ${rec.constraints.roas_floor.toFixed(1)}× required floor (${(k.blended_roas_projected - rec.constraints.roas_floor).toFixed(2)}×)`} />
            <BigMetric label="Net Contribution / Day"
              info="Projected incremental daily contribution margin — the objective the engine maximizes"
              current={money(k.net_contribution_current)} recommended={money(k.net_contribution_projected)}
              pill={`${netDelta >= 0 ? '+' : ''}${money(netDelta)}/day${k.net_contribution_current > 0 ? ` (${netDelta >= 0 ? '+' : ''}${netPct.toFixed(1)}%)` : ''} · the objective the engine maximizes`} />
          </div>
        </div>

        {/* Group 2 — contribution economics */}
        <div className="space-y-3">
          <GroupLabel title="Contribution economics" desc="the optimization lens beneath the headline ROAS" />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <BigMetric label="CM ROAS"
              info="Contribution margin per ad $ — the lens the optimizer actually maximizes; breaks even at 1.0×"
              current={`${k.cm_roas_current.toFixed(2)}×`} recommended={`${k.cm_roas_projected.toFixed(2)}×`}
              pill={`${cmDelta >= 0 ? '+' : ''}${cmDelta.toFixed(2)}× · contribution margin per ad $, breaks even at 1.0×`} />
          </div>
        </div>

        {/* Group 3 — policy guardrails (actual vs threshold, from the solver) */}
        <div className="space-y-3">
          <GroupLabel title="Policy guardrails" desc="constraints the plan must satisfy" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Guardrail label="Calibrated ROAS floor" detail={roasDetail} status={roasG?.status ?? 'slack'} />
            <Guardrail label="NC-CPA ceiling" detail={cpaDetail} status={cpaG?.status ?? 'slack'} />
            <Guardrail label="Prospecting floor" detail={prospDetail} status={prospG?.status ?? 'slack'} />
          </div>
        </div>

        {/* Group 4 — supporting context */}
        <div className="space-y-3">
          <GroupLabel title="Context" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <ContextCard label="Daily Spend" current={money(k.total_current_spend)} recommended={money(k.total_recommended_spend)}
              sub={k.total_recommended_spend <= k.total_current_spend + 1 ? 'equal-or-lower spend' : 'optimized investment profile'} />
            <ContextCard label="Reported ROAS" current={`${k.reported_roas_current.toFixed(2)}×`} recommended={`${k.reported_roas_projected.toFixed(2)}×`}
              sub="platform-reported · context" />
            <ContextCard label={`Reserve (${rec.constraints.reserve_mode === 'efficiency_first' ? 'efficiency-first' : 'growth'})`}
              recommended={money(k.reserve)} sub={k.reserve > 0 ? 'withheld below hurdle' : 'fully deployed'} />
          </div>
        </div>
      </div>

      {/* Chart + side panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white border border-[#cbd5e1]/50 rounded-xl p-5 shadow-sm hover:shadow-md transition-all flex flex-col">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6 select-none border-b border-slate-100 pb-4">
            <div>
              <span className="text-xs font-bold text-[#475569] tracking-wider uppercase block">Current vs Recommended Allocation</span>
              <span className="text-[10px] text-[#64748b] font-mono mt-1 block uppercase font-medium">
                {mode === 'movement' ? 'Per campaign · dollars moved per day' : mode === 'channel' ? 'By platform · daily spend' : 'By objective · daily spend'}
              </span>
            </div>
            <div className="flex bg-slate-100/80 p-0.5 rounded-lg border border-slate-200">
              {(['movement', 'channel', 'objective'] as const).map((m) => (
                <button key={m} onClick={() => setMode(m)}
                        className={`px-3 py-1.5 text-[10px] font-bold rounded-md transition-all duration-150 uppercase tracking-wider ${mode === m ? 'bg-white text-slate-900 shadow-sm border border-slate-200/50' : 'text-slate-500 hover:text-slate-900'}`}>
                  {m}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 flex flex-col justify-between pt-1 pb-1">
            {mode === 'movement'
              ? <MovementBars lines={rec.lines} />
              : <AllocationBars lines={rec.lines} mode={mode} />}
            {mode === 'movement' ? (
              <p className="text-[10px] sm:text-[11px] text-[#64748b] mt-6 pt-4 border-t border-slate-100 select-none leading-relaxed font-mono">
                DOLLARS MOVED PER DAY · CENTER LINE = NO CHANGE · <span className="text-emerald-600 font-bold uppercase">scale up</span> · <span className="text-rose-500 font-bold uppercase">pull back</span> · INVENTORY-HELD CAMPAIGNS ARE NOT INCREASED.
              </p>
            ) : (
              <div className="flex flex-wrap justify-start items-center gap-x-6 gap-y-2 mt-6 pt-4 border-t border-slate-100 select-none text-[10px] sm:text-xs font-bold text-[#64748b] uppercase tracking-widest font-sans">
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-slate-300 inline-block" /><span>Current / Retained</span></div>
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /><span>Recommended Scale Up</span></div>
                <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-rose-200 inline-block" /><span>Recommended Cut Back</span></div>
                <div className="flex items-center gap-1.5"><span className="w-0.5 h-3 border-l-2 border-dashed border-slate-400 inline-block" /><span>Daily Cap Space</span></div>
              </div>
            )}
          </div>
        </div>

        {/* Side panel: recommendation + approve + constraints */}
        <div className="flex flex-col gap-6">
          <div className="bg-[#131b2e] text-white rounded-xl p-6 shadow-sm flex flex-col gap-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs uppercase tracking-wider font-semibold text-[#dae2fd]">Engine Recommendation</span>
              {narration?.source === 'llm' && (
                <span title={`Narrated by ${narration.model}. Numbers are computed deterministically; the LLM only explains them.`}
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/10 text-[#c7d6f5] text-[10px] font-semibold tracking-wide">
                  <Sparkles size={10} /> AI narration
                </span>
              )}
            </div>
            {narrationLoading ? (
              <div className="flex items-center gap-2 text-sm text-[#9fb4d8] py-1">
                <Loader2 size={14} className="animate-spin text-[#9fb4d8]" />
                <span>Generating narration…</span>
              </div>
            ) : (
              <p className="text-sm leading-relaxed text-[#dae2fd]">{narration?.text ?? summary}</p>
            )}
            {approveBlockedReason && !decided && (
              <p className="text-[11px] text-[#fcd34d]">{approveBlockedReason}</p>
            )}
            <div className="pt-4 border-t border-white/15 flex gap-2">
              <button
                onClick={() => decide('approve')}
                disabled={busy || decided || approveBlockedReason !== null}
                className={`flex-1 text-xs font-semibold py-2.5 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed ${approved ? 'bg-[#00714d] text-white cursor-default flex items-center justify-center gap-1.5' : 'bg-white hover:bg-[#eef4ff] text-[#131b2e] active:scale-95'}`}>
                {approved ? (<><Check size={13} /><span>Recorded to ledger</span></>) : busy ? 'Recording…' : 'Approve plan'}
              </button>
              <button
                onClick={() => decide('reject')}
                disabled={busy || decided}
                className={`flex-1 text-xs font-semibold py-2.5 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed ${rejected ? 'bg-[#7f1d1d] text-white cursor-default flex items-center justify-center gap-1.5' : 'border border-[#fca5a5]/40 text-[#fca5a5] hover:bg-white/10 active:scale-95'}`}>
                {rejected ? (<><Ban size={13} /><span>Rejected</span></>) : 'Reject'}
              </button>
            </div>
            <button onClick={() => onNavigateToTab(ActiveTab.BudgetPlanner)}
                    className="text-[11px] text-[#9fb4d8] hover:text-white underline underline-offset-2 self-start transition-colors">
              View full plan in Budget Planner →
            </button>
            {approved && (
              <p className="text-[10px] text-[#9fb4d8]">
                Decision recorded to the append-only ledger. Execution payloads generated for review; external platform write-back is stubbed.
              </p>
            )}
            {rejected && (
              <p className="text-[10px] text-[#9fb4d8]">
                Rejection recorded to the ledger. No execution payloads were generated — nothing was sent to any platform.
              </p>
            )}
          </div>

          <div className="bg-white border border-[#e2e8f0] rounded-xl p-5 shadow-sm">
            <h4 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider mb-4 border-b border-[#e2e8f0] pb-2">
              Active Constraints &amp; Risks
            </h4>
            {binding.length === 0 && riskLines.length === 0 ? (
              <p className="text-xs text-[#45464d]">No binding constraints or risk flags — headroom available.</p>
            ) : (
              <ul className="space-y-4">
                {binding.map((b) => (
                  <li key={b.name} className="flex items-start gap-3">
                    <div className="bg-[#fef3c7] text-[#78350f] p-1.5 rounded-lg shrink-0"><AlertTriangle size={15} /></div>
                    <div>
                      <div className="text-xs font-semibold text-[#0d1c2d] font-data-mono">{b.name.replace(/_/g, ' ')} · {b.status}</div>
                      <div className="text-xs text-[#45464d] mt-0.5 leading-normal">{b.detail}</div>
                    </div>
                  </li>
                ))}
                {riskLines.map((l) => (
                  <li key={l.campaign_id} className="flex items-start gap-3">
                    <div className="bg-[#fee2e2] text-[#7f1d1d] p-1.5 rounded-lg shrink-0"><AlertOctagon size={15} /></div>
                    <div>
                      <div className="text-xs font-semibold text-[#0d1c2d] font-data-mono">{l.campaign_name}</div>
                      <div className="text-xs text-[#45464d] mt-0.5 leading-normal">{l.risk_flags.join(', ').replace(/_/g, ' ')}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      {/* Execution preview — only after approval: it's the record of the stubbed
          set-budget payloads the approved plan bound to. Hidden while pending/rejected
          (and therefore cleared by Reset, which reloads a fresh pending plan). */}
      {approved && <ExecutionPanel />}
    </div>
  );
}

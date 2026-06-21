import { useEffect, useState } from 'react';
import {
  Sliders,
  Filter,
  Download,
  CheckCircle,
  AlertTriangle,
  XCircle,
  CircleDot,
  Info,
  Loader2,
} from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';
import type { BindingItem, CampaignLine } from '../lib/api';
import { PlatformLogo } from './BrandLogo';

// Controlled number field that holds its own text while editing, so the user can
// clear it (empty string) or type an intermediate value without the displayed
// number snapping back to 0. It only commits a parsed number when one exists,
// and re-syncs to the incoming `value` when not focused (e.g. Reset to defaults).
function NumberInput({
  value,
  onCommit,
  parse = parseFloat,
  disabled,
  className,
  min,
  max,
  step,
}: {
  value: number;
  onCommit: (n: number) => void;
  parse?: (s: string) => number;
  disabled?: boolean;
  className?: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  const [text, setText] = useState(String(value));
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!editing) setText(String(value));
  }, [value, editing]);

  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      className={className}
      value={text}
      onFocus={() => setEditing(true)}
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        if (raw === '') return; // allow the field to be empty mid-edit
        const n = parse(raw);
        if (!Number.isNaN(n)) onCommit(n);
      }}
      onBlur={(e) => {
        setEditing(false);
        const n = parse(e.target.value);
        if (e.target.value === '' || Number.isNaN(n)) setText(String(value));
      }}
    />
  );
}

const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

const PACING_LABEL: Record<string, string> = {
  scale_opportunity: 'Leaving revenue on the table',
  capped_constrained: 'Capped — inventory-limited',
  strategic_floor: 'Retained for prospecting floor',
  pullback_candidate: 'Underperforming — reducing',
  waste_risk: 'Burning full budget',
  healthy: 'Healthy headroom',
};

const platformLogo = (platform: string) => <PlatformLogo platform={platform} />;

function FeasibilityCard({ item }: { item: BindingItem }) {
  const violated = item.status === 'violated';
  const binding = item.status === 'binding';
  const Icon = violated ? XCircle : binding ? AlertTriangle : CheckCircle;
  const color = violated ? 'text-red-600' : binding ? 'text-amber-600' : 'text-[#006c49]';
  const badge = violated
    ? 'bg-red-100 text-red-800'
    : binding
    ? 'bg-amber-100 text-amber-800'
    : 'bg-green-100 text-[#006c49]';
  return (
    <div className="p-3 border border-[#e2e8f0] rounded-lg bg-[#f8f9ff]/60 flex flex-col gap-1">
      <div className="flex justify-between items-start gap-2">
        <span className="text-xs font-semibold text-[#0d1c2d] capitalize">{item.name.replace(/_/g, ' ')}</span>
        <Icon size={15} className={`${color} shrink-0`} />
      </div>
      <div className="flex items-center gap-2 mt-1 pt-2 border-t border-[#e2e8f0]/40">
        <span className={`px-1 rounded-[3px] text-[8px] font-bold uppercase tracking-wider ${badge}`}>{item.status}</span>
        <span className="text-[10px] text-[#76777d] leading-tight">{item.detail}</span>
      </div>
    </div>
  );
}

export default function BudgetPlanner() {
  const { rec, cons, policy, loading, solving, error, decided, dirty, updateDraft, setPolicyDraft, recompute, reset } =
    useRecommendation();

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[#45464d] text-sm animate-fade-in">
        <Loader2 size={16} className="animate-spin text-[#00714d]" /> Loading optimizer…
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
  if (!rec || !cons) return null;

  const lines = rec.lines;
  const portfolio = rec.binding?.portfolio ?? [];
  const solver = rec.binding?.solver;

  // Edits are staged locally; "dirty" includes the in-flight solve, so the
  // button/indicator key off pending edits that have not been recomputed yet.
  const hasUnsavedEdits = dirty && !solving;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex justify-between items-end">
        <div>
          <div className="mb-1.5">
            <h2 className="text-2xl font-bold font-headline-lg text-[#0d1c2d] tracking-tight">Constraints &amp; Allocation</h2>
          </div>
          <p className="text-xs text-[#45464d] flex items-center gap-1.5 font-medium">
            <span className={`w-1.5 h-1.5 rounded-full ${rec.feasible ? 'bg-[#006c49]' : 'bg-red-600'}`} />
            Live optimizer · {rec.feasible ? 'feasible' : 'infeasible'} · policy {rec.policy_mode}
            {solving && <span className="inline-flex items-center gap-1 text-[#00714d]"><Loader2 size={11} className="animate-spin" /> solving…</span>}
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          {hasUnsavedEdits && (
            <span className="text-[11px] font-semibold text-[#b45309] bg-[#fffbeb] border border-[#fcd34d] rounded-md px-2 py-1 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[#d97706] animate-pulse" />
              Unsaved changes
            </span>
          )}
          <button onClick={reset} disabled={solving || decided}
                  className="text-xs px-3 py-1.5 border border-[#c6c6cd] rounded-lg hover:bg-[#f8f9ff] disabled:opacity-50">
            Reset to defaults
          </button>
          <button
            onClick={recompute}
            disabled={!hasUnsavedEdits || solving || decided}
            title="Run the optimizer on your edited constraints"
            className={`text-xs px-3.5 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
              hasUnsavedEdits && !solving && !decided
                ? 'bg-[#00714d] text-white hover:bg-[#005c3f] active:scale-95 shadow-sm'
                : 'bg-[#e2e8f0] text-[#76777d] cursor-not-allowed'
            }`}
          >
            {solving ? <Loader2 size={13} className="animate-spin" /> : <Sliders size={13} />}
            {solving ? 'Recomputing…' : 'Recompute plan'}
          </button>
        </div>
      </div>

      {decided && (
        <div className="bg-[#f1f5f9] border border-[#c6c6cd]/50 text-[#0f172a] rounded-lg px-4 py-2 text-xs">
          This scenario has been {rec.status}. Constraints are locked — reset to explore a new scenario.
        </div>
      )}

      {/* Constraint editor */}
      <div className="bg-white border border-[#e2e8f0] rounded-xl shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-[#e2e8f0] bg-[#f8f9ff] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sliders size={15} className="text-[#131b2e]" />
            <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">Main Constraint Panel</h3>
          </div>
          <span className="text-[10px] bg-[#eef4ff] text-[#131b2e] px-2 py-0.5 rounded-md font-semibold border border-[#dae2fd]">
            Draft → Recompute
          </span>
        </div>

        <div className="p-6 space-y-6">
          {/* Spend envelope is an OUTPUT here: the optimizer sets spend within the
              movement bounds; there is no settable budget pool in this model. */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pb-6 border-b border-[#e2e8f0]/60">
            <div className="bg-[#f8f9ff] border border-[#e2e8f0] rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-bold">Current daily spend</div>
              <div className="text-base font-bold font-data-mono text-[#0d1c2d]">{money(rec.kpis.total_current_spend)}</div>
            </div>
            <div className="bg-[#f8f9ff] border border-[#e2e8f0] rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-bold">Recommended daily spend</div>
              <div className="text-base font-bold font-data-mono text-[#0d1c2d]">{money(rec.kpis.total_recommended_spend)}</div>
            </div>
            <div className="bg-[#f8f9ff] border border-[#e2e8f0] rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-bold">Held in reserve</div>
              <div className="text-base font-bold font-data-mono text-[#0d1c2d]">{money(rec.kpis.reserve)}</div>
            </div>
          </div>

          {/* Safeguards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 pb-6 border-b border-[#e2e8f0]/60">
            <div className="space-y-2">
              <label className="text-xs font-bold text-[#45464d] uppercase tracking-wider block">Calibrated ROAS floor</label>
              <div className="flex items-center gap-2">
                <NumberInput min={1} max={10} step={0.1} value={cons.roas_floor} disabled={decided}
                       onCommit={(n) => updateDraft({ roas_floor: n })}
                       className="w-full text-xs font-semibold bg-[#f8f9ff] border border-[#c6c6cd] rounded-lg px-3 py-1.5 font-data-mono text-[#0d1c2d] focus:outline-none focus:border-[#00714d] focus:bg-white disabled:opacity-60" />
                <span className="text-xs font-bold text-[#45464d]">×</span>
              </div>
              <p className="text-[10px] text-[#76777d]">Enforced portfolio calibrated-ROAS floor (governance lens).</p>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-[#45464d] uppercase tracking-wider block">NC-CPA Ceiling</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 font-bold text-xs">$</span>
                <NumberInput min={5} max={200} value={cons.nc_cpa_target} disabled={decided}
                       parse={(s) => parseInt(s, 10)}
                       onCommit={(n) => updateDraft({ nc_cpa_target: n })}
                       className="w-full text-xs font-semibold bg-[#f8f9ff] border border-[#c6c6cd] rounded-lg pl-6 pr-3 py-1.5 font-data-mono text-[#0d1c2d] focus:outline-none focus:border-[#00714d] focus:bg-white disabled:opacity-60" />
              </div>
              <p className="text-[10px] text-[#76777d]">Maximum acceptable new-customer acquisition cost.</p>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-[#45464d] uppercase tracking-wider block">Min Prospecting Share</label>
              <div className="relative">
                <NumberInput min={0} max={80} value={Math.round(cons.prospecting_min_share * 100)} disabled={decided}
                       parse={(s) => parseInt(s, 10)}
                       onCommit={(n) => updateDraft({ prospecting_min_share: n / 100 })}
                       className="w-full text-xs font-semibold bg-[#f8f9ff] border border-[#c6c6cd] rounded-lg pl-3 pr-6 py-1.5 font-data-mono text-[#0d1c2d] focus:outline-none focus:border-[#00714d] focus:bg-white disabled:opacity-60" />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 font-bold text-xs">%</span>
              </div>
              <p className="text-[10px] text-[#76777d]">Minimum portion of spend held on prospecting.</p>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-[#45464d] uppercase tracking-wider block">Max Campaign Movement</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 font-bold text-xs">±</span>
                <NumberInput min={5} max={40} value={Math.round(cons.movement_bound * 100)} disabled={decided}
                       parse={(s) => parseInt(s, 10)}
                       onCommit={(n) => updateDraft({ movement_bound: n / 100 })}
                       className="w-full text-xs font-semibold bg-[#f8f9ff] border border-[#c6c6cd] rounded-lg pl-6 pr-6 py-1.5 font-data-mono text-[#0d1c2d] focus:outline-none focus:border-[#00714d] focus:bg-white disabled:opacity-60" />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 font-bold text-xs">%</span>
              </div>
              <p className="text-[10px] text-[#76777d]">
                Max allocation change per run{policy === 'conservative' ? ` · effective ±${Math.round(rec.effective_movement_bound * 100)}% (Conservative)` : ''}.
              </p>
            </div>
          </div>

          {/* Policy + reserve */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-1">
            <div className="space-y-2">
              <label className="text-xs font-bold text-[#45464d] uppercase tracking-wider block">Policy Mode</label>
              <div className="grid grid-cols-2 gap-2 bg-[#eef4ff] p-1 rounded-xl border border-[#c6c6cd]/20">
                {(['expected', 'conservative'] as const).map((p) => (
                  <button key={p} type="button" disabled={decided} onClick={() => setPolicyDraft(p)}
                          className={`py-2 text-xs font-semibold rounded-lg transition-colors disabled:opacity-60 ${policy === p ? 'bg-white text-[#0d1c2d] shadow-sm font-bold' : 'text-[#45464d] hover:text-[#0d1c2d]'}`}>
                    {p === 'expected' ? 'Expected' : 'Conservative'}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-[#76777d]">
                {policy === 'expected' ? 'Expected: point-estimate marginals.' : 'Conservative: downside marginals + tighter movement (75%).'}
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-[#45464d] uppercase tracking-wider block">Reserve Mode</label>
              <div className="grid grid-cols-2 gap-2 bg-[#eef4ff] p-1 rounded-xl border border-[#c6c6cd]/20">
                {(['growth', 'efficiency_first'] as const).map((m) => (
                  <button key={m} type="button" disabled={decided} onClick={() => updateDraft({ reserve_mode: m })}
                          className={`py-2 text-xs font-semibold rounded-lg transition-colors disabled:opacity-60 ${cons.reserve_mode === m ? 'bg-white text-[#0d1c2d] shadow-sm font-bold' : 'text-[#45464d] hover:text-[#0d1c2d]'}`}>
                    {m === 'growth' ? 'Growth' : 'Efficiency-first'}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-[#76777d]">
                {cons.reserve_mode === 'growth' ? 'Growth: deploy the full budget when feasible.' : 'Efficiency-first: hold money in reserve when no campaign clears its hurdle.'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Allocation table + feasibility */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-9 bg-white border border-[#e2e8f0] rounded-xl overflow-hidden shadow-sm flex flex-col">
          <div className="px-5 py-4 border-b border-[#e2e8f0] flex justify-between items-center bg-[#f8f9ff]">
            <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider flex items-center gap-2">
              <CircleDot size={14} className="text-[#0d1c2d]" /> Recommended Allocation Table
            </h3>
            <div className="flex gap-1.5 text-[#76777d]">
              <button className="p-1.5 hover:bg-white rounded border border-[#c6c6cd]/40"><Filter size={13} /></button>
              <button className="p-1.5 hover:bg-white rounded border border-[#c6c6cd]/40"><Download size={13} /></button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead className="bg-[#f8f9ff] border-b border-[#e2e8f0]">
                <tr>
                  <th className="py-2.5 px-4 text-[#45464d] font-semibold">Campaign / Platform</th>
                  <th className="py-2.5 px-3 text-[#45464d] font-semibold text-right">Current / day</th>
                  <th className="py-2.5 px-3 text-[#0d1c2d] font-bold text-right bg-[#eef4ff]/50">Rec. / day</th>
                  <th className="py-2.5 px-3 text-[#45464d] font-semibold text-right">% Change</th>
                  <th className="py-2.5 px-3 text-[#45464d] font-semibold text-right">Calib. ROAS</th>
                  <th className="py-2.5 px-3 text-[#45464d] font-semibold text-right">Gross Marginal ROAS</th>
                  <th className="py-2.5 px-3 text-[#45464d] font-semibold pl-4">Utilization</th>
                  <th className="py-2.5 px-4 text-[#45464d] font-semibold">Pacing</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0]/40 text-[#0d1c2d]">
                {lines.map((ln: CampaignLine) => {
                  const belowHurdle = ln.marginal_roas < ln.marginal_hurdle;
                  const util = Math.round(ln.current_utilization * 100);
                  return (
                    <tr key={ln.campaign_id} className="hover:bg-gray-50/50 transition-colors">
                      <td className="py-2.5 px-4 font-semibold whitespace-nowrap">
                        <div className="flex items-center gap-2">{platformLogo(ln.platform)}<span>{ln.campaign_name}</span></div>
                      </td>
                      <td className="py-2.5 px-3 font-data-mono text-right text-[#76777d]">{money(ln.current_spend)}</td>
                      <td className="py-2.5 px-3 font-bold font-data-mono text-right bg-[#eef4ff]/40">{money(ln.recommended_spend)}</td>
                      <td className={`py-2.5 px-3 font-data-mono text-right font-semibold ${ln.delta_pct >= 0 ? 'text-[#006c49]' : 'text-red-700'}`}>
                        {ln.delta_pct >= 0 ? '+' : ''}{ln.delta_pct}%
                      </td>
                      <td className="py-2.5 px-3 font-data-mono text-right">{ln.calibrated_roas_current.toFixed(2)}×</td>
                      <td className={`py-2.5 px-3 font-data-mono text-right ${belowHurdle ? 'text-red-700 font-semibold' : ''}`}
                          title={`hurdle ${ln.marginal_hurdle.toFixed(2)}×`}>
                        {ln.marginal_roas.toFixed(2)}×
                      </td>
                      <td className="py-2.5 px-3 pl-4">
                        <div className="flex items-center gap-2 w-24">
                          <div className="w-full bg-[#f8f9ff] h-1.5 rounded-full overflow-hidden border border-[#c6c6cd]/30">
                            <div className={`h-full rounded-full ${util > 95 ? 'bg-amber-600' : util < 50 ? 'bg-red-500' : 'bg-green-500'}`} style={{ width: `${Math.min(100, util)}%` }} />
                          </div>
                          <span className="font-data-mono text-[10px] text-[#76777d]">{util}%</span>
                        </div>
                      </td>
                      <td className="py-2.5 px-4 whitespace-nowrap">
                        <span className={`inline-flex px-2 py-0.5 rounded-sm text-[10px] font-semibold border ${
                          ln.pacing_flag === 'waste_risk' || ln.pacing_flag === 'pullback_candidate'
                            ? 'bg-red-50 text-red-800 border-red-200'
                            : ln.pacing_flag === 'capped_constrained' || ln.pacing_flag === 'scale_opportunity'
                            ? 'bg-[#fef3c7] text-[#92400E] border-[#fde68a]'
                            : 'bg-gray-100 text-gray-800 border-gray-200'
                        }`}>
                          {PACING_LABEL[ln.pacing_flag] ?? ln.pacing_flag}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Feasibility — straight from the solver's binding report */}
        <div className="lg:col-span-3">
          <div className="bg-white border border-[#e2e8f0] rounded-xl p-5 shadow-sm space-y-4">
            <div className="border-b border-[#e2e8f0] pb-3 mb-2">
              <h3 className="text-sm font-bold text-[#0d1c2d] flex items-center gap-1.5">
                {rec.feasible ? <CheckCircle size={16} className="text-[#006c49]" /> : <XCircle size={16} className="text-red-600" />}
                Feasibility Summary
              </h3>
              <p className="text-xs text-[#76777d] mt-1">
                Binding vs. slack constraints, from the optimizer.
                {solver && ` SLSQP ${solver.local_optimality_converged ? 'converged' : 'feasible candidate'} in ${solver.iterations} iters.`}
              </p>
            </div>
            {!rec.feasible && rec.conflicts.length > 0 && (
              <div className="bg-red-50 border border-red-200 text-red-800 rounded-lg p-2 text-[10px]">
                {rec.conflicts.map((c) => <div key={c}>• {c}</div>)}
              </div>
            )}
            <div className="space-y-3">
              {portfolio.length === 0 ? (
                <p className="text-xs text-[#76777d]">No portfolio constraints reported.</p>
              ) : (
                portfolio.map((b) => <div key={b.name}><FeasibilityCard item={b} /></div>)
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="pt-2 flex justify-end">
        <span className="text-xs text-[#76777d] italic flex items-center gap-1">
          <Info size={13} className="text-[#76777d]" />
          Stub execution — an approved plan is recorded to the append-only ledger; external platform write-back is stubbed.
        </span>
      </div>
    </div>
  );
}

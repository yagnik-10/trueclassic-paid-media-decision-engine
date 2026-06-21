import { useCallback, useEffect, useState } from 'react';
import {
  ExternalLink,
  X,
  AlertTriangle,
  MinusSquare,
  Shield,
  ShieldCheck,
  ShieldAlert,
  Copy,
  Check,
  Loader2,
  Link2,
  RefreshCw,
} from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';
import {
  getAuditLog,
  verifyAuditChain,
  type AuditChainStatus,
  type DecisionResponse,
} from '../lib/api';

const shortHash = (h: string) => (h ? `${h.slice(0, 10)}…${h.slice(-6)}` : '—');
const platformLabel = (p: string) =>
  p === 'meta' ? 'Meta Ads' : p === 'google' ? 'Google Ads' : p;

export default function AuditControls() {
  const { rec } = useRecommendation();
  const { decision } = useRecommendation();

  const [log, setLog] = useState<DecisionResponse[]>([]);
  const [chain, setChain] = useState<AuditChainStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<DecisionResponse | null>(null);
  const [isCopied, setIsCopied] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [entries, status] = await Promise.all([getAuditLog(), verifyAuditChain()]);
      setLog(entries);
      setChain(status);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Load on mount, and re-pull whenever a new decision lands (new ledger row).
  useEffect(() => {
    void refresh();
  }, [refresh, decision?.row_hash]);

  const runVerify = async () => {
    setVerifying(true);
    try {
      setChain(await verifyAuditChain());
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setVerifying(false);
    }
  };

  const handleCopyJson = (text: string) => {
    navigator.clipboard.writeText(text);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  // newest first for the table/timeline (ledger is stored oldest→newest)
  const entries = [...log].reverse();

  // Calibration provenance + inventory holds come from the ACTIVE plan (rec).
  const calib = rec?.calibration_registry ?? [];
  const inventoryHolds = (rec?.lines ?? []).filter((l) =>
    l.risk_flags.includes('inventory_no_scale'),
  );
  const sensitivity = rec?.is_sensitivity_override ?? false;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* View Header */}
      <header className="mb-4 flex flex-col sm:flex-row justify-between items-start sm:items-end gap-3">
        <div>
          <h1 className="text-2xl font-bold font-headline-lg text-[#0d1c2d] mb-1.5 leading-none tracking-tight">
            Audit &amp; Business Controls
          </h1>
          <p className="text-xs text-[#45464d] max-w-2xl leading-relaxed">
            The durable, append-only decision ledger — every approve/reject is hash-chained for
            tamper-evidence and survives restarts. Below: the live ledger, the calibration
            provenance applied to the active plan, and inventory holds enforced by the engine.
          </p>
        </div>

        {/* Hash-chain integrity pill + verify */}
        <div className="flex items-center gap-2 shrink-0">
          {chain && (
            <span
              className={`px-3 py-1.5 rounded-full flex items-center gap-1.5 border text-xs font-semibold ${
                chain.ok
                  ? 'bg-[#d1fae5] text-[#006c49] border-[#6cf8bb]/40'
                  : 'bg-red-50 text-red-800 border-red-200'
              }`}
              title={chain.ok ? `head ${chain.head_hash}` : `broken at seq ${chain.broken_seq}`}
            >
              {chain.ok ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
              {chain.ok
                ? `Chain verified · ${chain.count} record${chain.count === 1 ? '' : 's'}`
                : `Chain BROKEN at seq ${chain.broken_seq}`}
            </span>
          )}
          <button
            onClick={runVerify}
            disabled={verifying || loading}
            className="px-3 py-1.5 rounded-lg flex items-center gap-1.5 border border-[#c6c6cd] text-xs font-semibold text-[#131b2e] hover:bg-gray-100 transition-colors disabled:opacity-50"
          >
            {verifying ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Verify chain
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm">
          Could not reach the audit API: {error}
        </div>
      )}

      <div className="grid grid-cols-12 gap-6 items-start">
        {/* Left Column — ledger + trail */}
        <div className="col-span-12 xl:col-span-7 flex flex-col gap-6">
          {/* Scenario / decision history */}
          <section className="bg-white border border-[#e2e8f0] rounded-xl overflow-hidden shadow-sm">
            <div className="px-4 py-3 border-b border-[#e2e8f0] flex justify-between items-center bg-[#f8f9ff]">
              <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">
                Decision Ledger (Append-Only)
              </h3>
              <span className="text-[10px] text-[#76777d] font-data-mono">
                {entries.length} record{entries.length === 1 ? '' : 's'}
              </span>
            </div>

            <div className="overflow-x-auto">
              {loading ? (
                <div className="p-6 text-sm text-[#45464d] flex items-center gap-2">
                  <Loader2 size={15} className="animate-spin text-[#00714d]" /> Loading ledger…
                </div>
              ) : entries.length === 0 ? (
                <div className="p-6 text-sm text-[#45464d]">
                  No decisions recorded yet. Approve or reject a plan to write the first ledger row.
                </div>
              ) : (
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-[#e2e8f0]/80">
                      <th className="px-4 py-2 text-[#45464d] font-semibold">#</th>
                      <th className="px-4 py-2 text-[#45464d] font-semibold">Scenario</th>
                      <th className="px-4 py-2 text-[#45464d] font-semibold">Decided</th>
                      <th className="px-4 py-2 text-[#45464d] font-semibold">By</th>
                      <th className="px-4 py-2 text-[#45464d] font-semibold">Status</th>
                      <th className="px-4 py-2 text-[#45464d] font-semibold text-right">Record</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e2e8f0]/40 text-[#0d1c2d]">
                    {entries.map((d) => {
                      const isApproved = d.status === 'approved';
                      return (
                        <tr key={d.row_hash || d.scenario_id} className="hover:bg-gray-50/50 transition-colors h-10">
                          <td className="px-4 py-2 font-data-mono text-[#76777d]">{d.ledger_seq}</td>
                          <td className="px-4 py-2 font-semibold font-data-mono" title={d.scenario_id}>
                            {d.scenario_id.slice(0, 14)}…
                          </td>
                          <td className="px-4 py-2 font-data-mono text-[#76777d]">{d.decided_at.replace('T', ' ').slice(0, 19)}</td>
                          <td className="px-4 py-2 text-[#45464d]">{d.approver}</td>
                          <td className="px-4 py-2">
                            <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[9px] font-bold uppercase tracking-wider border ${
                              isApproved
                                ? 'bg-[#d1fae5] text-[#006c49] border-[#6cf8bb]/30'
                                : 'bg-red-50 text-red-800 border-red-200'
                            }`}>
                              {d.status}
                            </span>
                          </td>
                          <td className="px-4 py-2 text-right">
                            <button
                              onClick={() => setSelected(d)}
                              className="text-[#00714d] hover:underline inline-flex items-center gap-1 font-semibold font-data-mono"
                            >
                              <span>JSON</span>
                              <ExternalLink size={11} />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          {/* Hash-chain lineage trail */}
          <section className="bg-white border border-[#e2e8f0] rounded-xl p-6 shadow-sm">
            <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider border-b border-[#e2e8f0] pb-3 mb-6 flex items-center gap-2">
              <Link2 size={13} className="text-[#00714d]" /> Hash-Chain Lineage
            </h3>

            {entries.length === 0 ? (
              <p className="text-xs text-[#45464d]">No links yet — the chain starts at the genesis hash.</p>
            ) : (
              <div className="relative pl-6 space-y-6">
                <div className="absolute left-[11px] top-1.5 bottom-1.5 w-0.5 bg-[#e2e8f0]" />
                {entries.map((d) => (
                  <div key={d.row_hash} className="relative group">
                    <span className="absolute -left-[30px] top-1 w-3 h-3 rounded-full bg-white border-2 border-[#006c49] scale-110 group-hover:bg-[#006c49] transition-all" />
                    <div className="flex justify-between items-start gap-4">
                      <div className="min-w-0">
                        <div className="text-xs font-semibold text-[#0d1c2d]">
                          #{d.ledger_seq} · {d.status} by {d.approver}
                          {d.execution_events.length > 0 && (
                            <span className="text-[#76777d] font-normal">
                              {' '}· {d.execution_events.length} platform payload
                              {d.execution_events.length === 1 ? '' : 's'}
                            </span>
                          )}
                        </div>
                        <p className="text-[10px] text-[#76777d] mt-1 font-data-mono leading-relaxed break-all">
                          prev {shortHash(d.prev_hash)} → <b className="text-[#0d1c2d]">row {shortHash(d.row_hash)}</b>
                        </p>
                        {d.notes && <p className="text-[11px] text-[#45464d] mt-1 italic">“{d.notes}”</p>}
                      </div>
                      <span className="text-[10px] font-semibold font-data-mono text-[#76777d] shrink-0">
                        {d.decided_at.replace('T', ' ').slice(0, 19)}
                      </span>
                    </div>
                  </div>
                ))}
                {/* genesis anchor */}
                <div className="relative">
                  <span className="absolute -left-[30px] top-1 w-3 h-3 rounded-full bg-white border-2 border-[#76777d]" />
                  <div className="text-[10px] text-[#76777d] font-data-mono">genesis · {'0'.repeat(10)}…000000</div>
                </div>
              </div>
            )}
          </section>
        </div>

        {/* Right Column — calibration + inventory */}
        <div className="col-span-12 xl:col-span-5 flex flex-col gap-6">
          {/* Calibration provenance (applied to active plan) */}
          <section className="bg-white border border-[#e2e8f0] rounded-xl overflow-hidden shadow-sm">
            <div className="px-4 py-3 border-b border-[#e2e8f0] bg-[#f8f9ff] flex justify-between items-center">
              <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">
                Calibration — applied to active plan
              </h3>
              {sensitivity && (
                <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#fef3c7] text-[#78350f] border border-[#fcd34d]/50">
                  Sensitivity
                </span>
              )}
            </div>

            <div className="p-4 space-y-4">
              <div className="overflow-x-auto border border-[#e2e8f0] rounded-lg">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-[#e2e8f0]">
                      <th className="py-2.5 px-3 text-[#45464d] font-semibold">Segment</th>
                      <th className="py-2.5 px-3 text-[#45464d] font-semibold text-right">Approved</th>
                      <th className="py-2.5 px-3 text-[#45464d] font-semibold text-right">Effective</th>
                      <th className="py-2.5 px-3 text-[#45464d] font-semibold">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e2e8f0]/60 text-[#0d1c2d]">
                    {calib.length === 0 ? (
                      <tr><td colSpan={4} className="py-3 px-3 text-[#76777d]">No calibration rows for this plan.</td></tr>
                    ) : (
                      calib.map((c) => (
                        <tr key={c.registry_id} className="hover:bg-gray-50/40 h-9 transition-colors">
                          <td className="py-2 px-3 font-semibold">{c.segment.replace(/_/g, ' ')}</td>
                          <td className="py-2 px-3 text-right font-data-mono text-[#76777d]">{c.approved_coefficient.toFixed(2)}</td>
                          <td className={`py-2 px-3 text-right font-data-mono font-bold ${c.overridden ? 'text-red-700' : 'text-[#0d1c2d]'}`}>
                            {c.coefficient.toFixed(2)}{c.overridden && ' *'}
                          </td>
                          <td className="py-2 px-3 text-[#45464d] text-[11px]">
                            {c.source}{c.is_synthetic && <span className="text-[#a6a6ad]"> · synthetic</span>}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <div className="border p-4 rounded-xl bg-amber-50/30 border-amber-300/40">
                <div className="flex items-start gap-2.5">
                  <AlertTriangle className="shrink-0 text-[#78350f]" size={16} />
                  <div>
                    <h5 className="text-xs font-bold text-[#78350f]">Coefficients are registry-governed</h5>
                    <p className="text-xs text-[#45464d] mt-1 leading-normal">
                      These are the incrementality coefficients <b>actually applied</b> to the active
                      plan. To explore alternatives, run a <b>sensitivity what-if</b> (New Optimization →
                      calibration overrides) — a sensitivity plan is flagged and can never be approved
                      or executed. Approving a revised coefficient means promoting it in the registry.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* Inventory holds enforced on the active plan */}
          <section className="bg-white border border-[#e2e8f0] rounded-xl overflow-hidden shadow-sm flex-1">
            <div className="px-4 py-3 border-b border-[#e2e8f0] bg-[#f8f9ff]">
              <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">
                Inventory Handoff Constraints
              </h3>
            </div>

            {inventoryHolds.length === 0 ? (
              <p className="p-4 text-xs text-[#45464d]">
                No active inventory holds — no campaign is blocked from scaling on supply.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-[#e2e8f0]">
                      <th className="py-2 px-4 text-[#45464d] font-semibold">Campaign</th>
                      <th className="py-2 px-4 text-[#45464d] font-semibold">Platform</th>
                      <th className="py-2 px-4 text-[#45464d] font-semibold">Action Enforced</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#e2e8f0]/50 text-[#0d1c2d]">
                    {inventoryHolds.map((l) => (
                      <tr key={l.campaign_id} className="hover:bg-gray-50/50 transition-colors h-11">
                        <td className="py-2 px-4 font-semibold">{l.campaign_name}</td>
                        <td className="py-2 px-4 text-[#45464d]">{platformLabel(l.platform)}</td>
                        <td className="py-2 px-4">
                          <div className="flex items-center gap-1.5 text-red-700">
                            <MinusSquare size={14} className="shrink-0" />
                            <span className="text-[10px] font-bold uppercase leading-tight">
                              Scaling blocked (inventory)
                            </span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>

      {/* Real decision-record JSON modal */}
      {selected && (
        <div className="fixed inset-0 bg-[#131b2e]/60 backdrop-blur-xs flex items-center justify-center z-50 animate-fade-in p-4">
          <div className="bg-white rounded-xl max-w-2xl w-full flex flex-col shadow-2xl border border-[#e2e8f0]">
            <div className="p-4 border-b border-[#e2e8f0] flex justify-between items-center bg-[#f8f9ff] rounded-t-xl">
              <div className="flex items-center gap-2">
                <Shield size={16} className="text-[#00714d]" />
                <span className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider font-data-mono">
                  Ledger record #{selected.ledger_seq} — {selected.scenario_id.slice(0, 14)}…
                </span>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="text-[#76777d] hover:text-[#0d1c2d] p-1 rounded-full hover:bg-gray-100 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-5 overflow-y-auto max-h-[420px] bg-[#1d2433] text-white font-data-mono text-xs rounded-b-sm select-text selection:bg-[#00714d]">
              <pre className="whitespace-pre-wrap">{JSON.stringify(selected, null, 2)}</pre>
            </div>

            <div className="p-4 border-t border-[#e2e8f0] bg-[#f8f9ff] flex justify-end gap-2.5 rounded-b-xl">
              <button
                onClick={() => handleCopyJson(JSON.stringify(selected, null, 2))}
                className="px-3.5 py-1.5 flex items-center gap-1.5 text-xs font-semibold text-[#131b2e] hover:bg-gray-100 border border-[#c6c6cd] rounded-lg transition-all"
              >
                {isCopied ? (
                  <><Check size={13} className="text-green-600" /><span>Copied!</span></>
                ) : (
                  <><Copy size={13} /><span>Copy to Clipboard</span></>
                )}
              </button>
              <button
                onClick={() => setSelected(null)}
                className="px-4 py-1.5 text-xs font-semibold bg-[#131b2e] text-white hover:bg-[#233143] rounded-lg transition-all"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

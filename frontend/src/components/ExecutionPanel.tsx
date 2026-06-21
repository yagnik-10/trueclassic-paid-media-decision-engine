import { useEffect, useState } from 'react';
import { ArrowRight, ShieldCheck, FileLock2, Loader2, Ban, CheckCircle2, Hash } from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';
import { getExecutionPreview, type ExecutionPreview } from '../lib/api';

const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

const platformLabel = (p: string) =>
  p === 'meta' ? 'Meta Ads' : p === 'google' ? 'Google Ads' : p;

const shortHash = (h: string) => `${h.slice(0, 10)}…${h.slice(-6)}`;

// What WOULD (or DID) get pushed to Meta/Google on approval. The payloads come straight
// from the engine's stubbed builder, so the previewed hashes are byte-identical to the
// hashes committed to the audit ledger. No live write ever happens.
export default function ExecutionPanel() {
  const { rec, decision, dirty, solving } = useRecommendation();
  const [preview, setPreview] = useState<ExecutionPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const scn = rec?.scenario_id ?? null;
  const stale = dirty || solving;

  useEffect(() => {
    if (!scn || stale) return;
    let cancelled = false;
    setLoading(true);
    getExecutionPreview(scn)
      .then((p) => !cancelled && (setPreview(p), setErr(null)))
      .catch((e) => !cancelled && setErr(e?.message ?? String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [scn, stale]);

  if (!rec) return null;

  const approved = decision?.status === 'approved';
  const rejected = decision?.status === 'rejected';
  // committed hashes (post-approval) — used to mark previewed payloads as recorded
  const committed = new Map((decision?.execution_events ?? []).map((e) => [e.event_id, e]));

  return (
    <div className="bg-white border border-[#e2e8f0] rounded-xl p-6 shadow-sm animate-fade-in">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-1">
        <div>
          <h3 className="text-lg font-bold text-[#0d1c2d] tracking-tight flex items-center gap-2">
            <FileLock2 size={18} className="text-[#00714d]" />
            Execution preview — stubbed platform write-back
          </h3>
          <p className="text-xs text-[#76777d] mt-0.5">
            The exact set-budget calls approval binds to. Each payload hash matches the hash
            committed to the append-only ledger — verify before approving.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-[#fef3c7] text-[#78350f] text-xs font-semibold border border-[#fcd34d]/50 shrink-0">
          <Ban size={12} /> No live write
        </span>
      </div>

      {/* status / staleness banners */}
      {stale ? (
        <div className="mt-4 text-sm text-[#45464d] flex items-center gap-2">
          <Loader2 size={15} className="animate-spin text-[#00714d]" />
          Inputs changed — recompute the plan to refresh the execution preview.
        </div>
      ) : err ? (
        <div className="mt-4 bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-lg p-3 text-sm">
          Could not load execution preview: {err}
        </div>
      ) : loading && !preview ? (
        <div className="mt-4 text-sm text-[#45464d] flex items-center gap-2">
          <Loader2 size={15} className="animate-spin text-[#00714d]" /> Building payloads…
        </div>
      ) : !preview ? null : (
        <div className="mt-4 space-y-4">
          {approved && (
            <div className="bg-[#d1fae5] border border-[#6cf8bb]/50 text-[#006c49] rounded-lg p-3 text-sm flex items-center gap-2">
              <CheckCircle2 size={16} />
              <span>
                Recorded to the ledger by <b>{decision?.approver}</b>. {committed.size} platform
                payload{committed.size === 1 ? '' : 's'} generated — hashes match this preview.
              </span>
            </div>
          )}
          {rejected && (
            <div className="bg-[#f1f5f9] border border-[#c6c6cd]/50 text-[#334155] rounded-lg p-3 text-sm flex items-center gap-2">
              <Ban size={16} />
              <span>
                Rejected by <b>{decision?.approver}</b> — these calls were <b>not</b> sent and
                nothing was committed.
              </span>
            </div>
          )}

          {preview.total_changes === 0 ? (
            <p className="text-sm text-[#45464d]">
              No budget changes in this plan — nothing would be pushed.
            </p>
          ) : (
            <>
              <div className="text-xs text-[#76777d]">
                {preview.total_changes} budget change{preview.total_changes === 1 ? '' : 's'} across{' '}
                {preview.payloads.length} platform{preview.payloads.length === 1 ? '' : 's'}.
              </div>
              <div className={`space-y-4 ${rejected ? 'opacity-50' : ''}`}>
                {preview.payloads.map((pl) => {
                  const ev = committed.get(pl.event_id);
                  return (
                    <div key={pl.event_id} className="border border-[#e2e8f0] rounded-lg overflow-hidden">
                      <div className="flex flex-wrap justify-between items-center gap-2 bg-[#f8fafc] px-4 py-2 border-b border-[#e2e8f0]">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold text-[#0d1c2d]">{platformLabel(pl.platform)}</span>
                          <span className="font-data-mono text-[11px] text-[#76777d]">{pl.event_id}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-1 font-data-mono text-[11px] text-[#45464d]" title={pl.payload_hash}>
                            <Hash size={11} className="text-[#a6a6ad]" />
                            {shortHash(pl.payload_hash)}
                          </span>
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold border ${ev ? 'bg-[#d1fae5] text-[#006c49] border-[#6cf8bb]/50' : 'bg-[#eef2f7] text-[#475569] border-[#c6c6cd]/40'}`}>
                            {ev ? <><ShieldCheck size={11} /> {ev.status}</> : 'stub · pending'}
                          </span>
                        </div>
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-[10px] uppercase tracking-wider text-[#76777d] text-left">
                            <th className="font-semibold px-4 py-1.5">Campaign</th>
                            <th className="font-semibold px-2 py-1.5 text-right">Current / day</th>
                            <th className="font-semibold px-2 py-1.5 text-center">→</th>
                            <th className="font-semibold px-2 py-1.5 text-right">New / day</th>
                            <th className="font-semibold px-4 py-1.5 text-right">Δ</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pl.changes.map((c) => {
                            const up = c.new_daily_budget >= c.current_spend;
                            return (
                              <tr key={c.campaign_id} className="border-t border-[#f1f5f9]">
                                <td className="px-4 py-2">
                                  <div className="font-semibold text-[#0d1c2d] leading-tight">{c.campaign_name}</div>
                                  <div className="font-data-mono text-[10px] text-[#a6a6ad]">{c.campaign_id}</div>
                                </td>
                                <td className="px-2 py-2 text-right font-data-mono text-[#76777d]">{money(c.current_spend)}</td>
                                <td className="px-2 py-2 text-center text-[#a6a6ad]"><ArrowRight size={13} className="inline" /></td>
                                <td className="px-2 py-2 text-right font-data-mono font-bold text-[#0d1c2d]">{money(c.new_daily_budget)}</td>
                                <td className={`px-4 py-2 text-right font-data-mono font-bold ${up ? 'text-[#0ca68f]' : 'text-[#ea4335]'}`}>
                                  {c.delta_pct >= 0 ? '+' : ''}{c.delta_pct.toFixed(1)}%
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {(preview.held_flat.length > 0 || preview.inventory_blocked.length > 0) && (
            <div className="text-[11px] text-[#76777d] space-y-1 pt-1">
              {preview.inventory_blocked.length > 0 && (
                <p>
                  <b className="text-[#78350f]">Suppressed (inventory):</b>{' '}
                  {preview.inventory_blocked.join(', ')} — recommended change withheld; not pushed.
                </p>
              )}
              {preview.held_flat.length > 0 && (
                <p>
                  <b>Held flat:</b> {preview.held_flat.length} campaign
                  {preview.held_flat.length === 1 ? '' : 's'} unchanged — no call sent.
                </p>
              )}
            </div>
          )}

          <p className="text-[11px] text-[#a6a6ad] leading-relaxed border-t border-[#f1f5f9] pt-3">
            {preview.note}
          </p>
        </div>
      )}
    </div>
  );
}

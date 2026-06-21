import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import {
  Loader2,
  AlertTriangle,
  CheckCircle,
  ShieldAlert,
  Trophy,
  FlaskConical,
  LineChart,
} from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';
import {
  getModelEvidence,
  type ModelEvidenceResponse,
  type ChampionCampaign,
  type ForecastSeriesPoint,
} from '../lib/api';

const LEAD_CAMPAIGN = 'GOOGLE_PMAX';

const money = (n: number) =>
  Math.abs(n) >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(2)}M`
    : Math.abs(n) >= 1_000
    ? `$${Math.round(n / 1_000)}k`
    : `$${Math.round(n)}`;

const fmtDay = (iso: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

const modelLabel = (m: string) =>
  m.startsWith('xgboost')
    ? 'XGBoost'
    : m === 'baseline_trailing_14d'
    ? 'Trailing 14-day'
    : m === 'baseline_same_weekday'
    ? 'Same weekday'
    : m === 'selected'
    ? 'Champion'
    : m;

const wapePct = (w: number | null | undefined) =>
  w === null || w === undefined ? '—' : `${(w * 100).toFixed(1)}%`;

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

// A simple horizontal WAPE bar (lower is better). `winner` paints it green; `drift` red.
function WapeBar({ label, wape, max, winner, drift, champion }: {
  label: string; wape: number | null; max: number; winner?: boolean; drift?: boolean; champion?: boolean;
}) {
  const pctW = wape !== null && max > 0 ? (wape / max) * 100 : 0;
  const color = drift ? 'bg-red-500' : winner ? 'bg-[#00a76f]' : 'bg-[#94a3b8]';
  return (
    <div className="space-y-1">
      <div className="flex justify-between items-baseline text-xs">
        <span className={`font-semibold flex items-center gap-1.5 ${champion ? 'text-[#0d1c2d]' : 'text-[#45464d]'}`}>
          {champion && <Trophy size={12} className="text-[#b45309]" />}
          {label}
          {champion && <span className="text-[9px] font-bold uppercase tracking-wider text-[#b45309] bg-amber-50 border border-amber-200 rounded px-1 py-0.5">Champion</span>}
        </span>
        <span className={`font-bold font-data-mono ${drift ? 'text-red-700' : 'text-[#0d1c2d]'}`}>{wapePct(wape)}</span>
      </div>
      <div className="w-full bg-[#f1f5f9] h-3 rounded-md overflow-hidden border border-gray-100">
        <div className={`h-full rounded-md transition-all duration-300 ${color}`} style={{ width: `${pctW}%` }} />
      </div>
    </div>
  );
}

// Forecast-vs-actual over the untouched test window: deployed P10–P90 band, the P50
// (== selected champion) line, and the realized holdout actuals. The story beat: "does
// the forecast track reality, and do the actuals sit inside the band?"
function ForecastFanChart({ series }: { series: ForecastSeriesPoint[] }) {
  const W = 500;
  const H = 230;
  const lo = Math.min(...series.map((p) => Math.min(p.p10, p.actual)));
  const hi = Math.max(...series.map((p) => Math.max(p.p90, p.actual)));
  const pad = Math.max(1, (hi - lo) * 0.08);
  const y0 = lo - pad;
  const y1 = hi + pad;
  const n = series.length;
  const sx = (i: number) => (n <= 1 ? W / 2 : (i / (n - 1)) * W);
  const sy = (v: number) => H - ((v - y0) / (y1 - y0)) * H;

  const bandTop = series.map((p, i) => `${sx(i)},${sy(p.p90)}`).join(' ');
  const bandBot = series.map((p, i) => `${sx(i)},${sy(p.p10)}`).reverse().join(' ');
  const p50Line = series.map((p, i) => `${sx(i)},${sy(p.p50)}`).join(' ');

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ idx: number; xPct: number } | null>(null);
  const onMove = (e: ReactMouseEvent) => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - r.left - 48) / (r.width - 56)));
    setHover({ idx: Math.round(frac * (n - 1)), xPct: ((e.clientX - r.left) / r.width) * 100 });
  };
  const hp = hover ? series[Math.max(0, Math.min(n - 1, hover.idx))] : null;
  const yTicks = [y1, (y1 + y0) / 2, y0];

  return (
    <div ref={wrapRef} className="flex-1 relative w-full h-full mt-3"
         onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      {hp && (
        <div className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-md bg-[#0d1c2d] text-white text-[10px] font-semibold px-2 py-1 shadow-lg whitespace-nowrap leading-tight"
             style={{ left: `clamp(60px, ${hover!.xPct}%, calc(100% - 60px))` }}>
          <div className="font-bold mb-0.5">{fmtDay(hp.date)}</div>
          <div>actual {money(hp.actual)}{hp.covered ? ' · in band' : ' · outside'}</div>
          <div className="text-[#9aa6bd]">P50 {money(hp.p50)} · band {money(hp.p10)}–{money(hp.p90)}</div>
        </div>
      )}
      <div className="absolute inset-0 flex flex-col justify-between pt-1 pb-6 pl-12 pr-2">
        {yTicks.map((t, i) => (
          <div key={i} className="border-t border-[#e2e8f0]/50 w-full relative">
            <span className="absolute -left-11 -top-2 text-[10px] font-semibold font-data-mono text-[#76777d]">{money(t)}</span>
          </div>
        ))}
      </div>
      <svg className="absolute inset-0 w-full h-full pb-6 pl-12 pr-2 pt-1" preserveAspectRatio="none" viewBox={`0 0 ${W} ${H}`}>
        <polygon points={`${bandTop} ${bandBot}`} fill="#3bc6c2" opacity={0.18} />
        <polyline points={p50Line} fill="none" stroke="#006c49" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        {hover && hp && (
          <line x1={sx(hover.idx)} y1={0} x2={sx(hover.idx)} y2={H} stroke="#0d1c2d" strokeWidth={1} strokeDasharray="2,2" opacity={0.35} vectorEffect="non-scaling-stroke" />
        )}
        {series.map((p, i) => (
          <circle key={i} cx={sx(i)} cy={sy(p.actual)} r={3} vectorEffect="non-scaling-stroke"
                  fill={p.covered ? '#0d1c2d' : '#ba1a1a'} stroke="#fff" strokeWidth={1} />
        ))}
      </svg>
      <div className="absolute bottom-0 left-12 right-2 flex justify-between text-[9px] font-semibold font-data-mono text-[#76777d]">
        <span>{series.length ? fmtDay(series[0].date) : ''}</span>
        <span>{series.length ? fmtDay(series[series.length - 1].date) : ''}</span>
      </div>
    </div>
  );
}

// Actual vs predicted on the untouched test: each holdout point against the 45° perfect
// line. Points on the line = accurate; spread = error. Coloured by band coverage. The axes
// ZOOM to the shared data range (not 0-anchored) so the deviation from the diagonal — e.g.
// systematic over-prediction — is legible instead of collapsing into a high-value corner.
function ActualVsPredictedChart({ series }: { series: ForecastSeriesPoint[] }) {
  const W = 260;
  const H = 230;
  const vals = series.flatMap((p) => [p.actual, p.pred]);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = Math.max(1, (hi - lo) * 0.1);
  lo -= pad;
  hi += pad;
  const span = hi - lo || 1;
  // square the domain so the 45° line stays a true diagonal under the W×H aspect
  const sx = (v: number) => ((v - lo) / span) * W;
  const sy = (v: number) => H - ((v - lo) / span) * H;
  // mean signed bias (pred − actual): positive = over-prediction
  const bias = series.reduce((s, p) => s + (p.pred - p.actual), 0) / (series.length || 1);
  const [hover, setHover] = useState<ForecastSeriesPoint | null>(null);

  return (
    <div className="flex-1 relative w-full h-full mt-3">
      {hover && (
        <div className="pointer-events-none absolute top-0 right-2 z-10 rounded-md bg-[#0d1c2d] text-white text-[10px] font-semibold px-2 py-1 shadow-lg whitespace-nowrap leading-tight">
          <div className="font-bold mb-0.5">{fmtDay(hover.date)}</div>
          <div>actual {money(hover.actual)}</div>
          <div className="text-[#9aa6bd]">predicted {money(hover.pred)}</div>
        </div>
      )}
      <svg className="absolute inset-0 w-full h-full p-1" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
           onMouseLeave={() => setHover(null)}>
        {/* perfect-recovery diagonal across the zoomed window (y = x) */}
        <line x1={sx(lo)} y1={sy(lo)} x2={sx(hi)} y2={sy(hi)} stroke="#ba1a1a" strokeWidth={1} strokeDasharray="4,4" vectorEffect="non-scaling-stroke" />
        {series.map((p, i) => (
          <circle key={i} cx={sx(p.actual)} cy={sy(p.pred)} r={4} vectorEffect="non-scaling-stroke"
                  fill={p.covered ? '#3bc6c2' : '#ba1a1a'} opacity={0.7} stroke="#0d1c2d" strokeWidth={0.4}
                  onMouseEnter={() => setHover(p)} style={{ cursor: 'pointer' }} />
        ))}
      </svg>
      {/* axis magnitude ticks (zoomed window bounds) */}
      <span className="absolute left-1 bottom-4 text-[9px] font-data-mono text-[#aeb0b6]">{money(lo)}</span>
      <span className="absolute right-2 bottom-4 text-[9px] font-data-mono text-[#aeb0b6]">{money(hi)}</span>
      <span className="absolute bottom-1 right-2 text-[9px] font-semibold text-[#76777d]">actual →</span>
      <span className="absolute top-1 left-1 text-[9px] font-semibold text-[#76777d]">↑ predicted</span>
      {/* mean-bias label: which side of the diagonal the cloud sits on */}
      <span className={`absolute top-1 right-2 text-[9px] font-semibold font-data-mono px-1.5 py-0.5 rounded border ${
        Math.abs(bias) < 1 ? 'text-[#45464d] bg-[#f1f5f9] border-[#e2e8f0]'
          : bias > 0 ? 'text-[#b45309] bg-amber-50 border-amber-200'
          : 'text-[#0369a1] bg-sky-50 border-sky-200'
      }`} title="Mean signed error (pred − actual): above the line = over-prediction, below = under-prediction.">
        {bias >= 0 ? '+' : ''}{money(bias)} {bias > 0 ? 'over' : 'under'}
      </span>
    </div>
  );
}

export default function ModelEvidence() {
  const { decision } = useRecommendation();
  const [data, setData] = useState<ModelEvidenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string>(LEAD_CAMPAIGN);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getModelEvidence());
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, decision?.row_hash]);

  const selected: ChampionCampaign | undefined = useMemo(() => {
    if (!data) return undefined;
    return data.campaigns.find((c) => c.campaign_id === selectedId) ?? data.campaigns[0];
  }, [data, selectedId]);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-[#45464d] text-sm animate-fade-in">
        <Loader2 size={16} className="animate-spin text-[#00714d]" /> Loading model evidence…
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm animate-fade-in">
        <b>Could not load the model evidence.</b> ({error})
        <p className="mt-1 text-xs text-[#7f1d1d]/80">
          If the report has not been generated yet, run <code>make model-report</code>.
        </p>
      </div>
    );
  }
  if (!data || !selected) return null;

  const p = data.provenance;
  const s = data.summary;

  // pre-test selection bars (frozen folds) — ONLY the two persisted bars; never test metrics.
  const pre = selected.pretest;
  const preMax = pre ? Math.max(pre.xgb_wape, pre.best_baseline_wape) * 1.1 : 1;
  const xgbWinsPre = pre ? pre.xgb_wape <= pre.best_baseline_wape : false;

  // untouched-test bars — all three models; the champion is highlighted, drift flagged.
  const testMax = Math.max(...selected.test_points.map((t) => t.wape ?? 0), 1e-9) * 1.1;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Module title + provenance badges */}
      <div className="flex flex-col lg:flex-row justify-between items-start lg:items-end gap-4">
        <div>
          <h2 className="text-2xl font-bold font-headline-lg text-[#0d1c2d] tracking-tight">
            Model Evidence
          </h2>
          <p className="text-sm text-[#45464d] mt-1 max-w-3xl">
            How each campaign's forecast champion was chosen — and how it held up on the untouched test.
            Interactive for exploration, read-only for methodology: nothing here re-picks a model.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-semibold border bg-[#f1f5f9] text-[#0f172a] border-[#c6c6cd]/40">
            profile <span className="font-data-mono">{p.dataset_profile}</span>
          </span>
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-semibold border bg-[#f1f5f9] text-[#0f172a] border-[#c6c6cd]/40">
            engine <span className="font-data-mono">{p.engine_version}</span>
          </span>
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-semibold border bg-[#f1f5f9] text-[#0f172a] border-[#c6c6cd]/40"
                title={`evidence_input_fingerprint ${p.evidence_input_fingerprint}`}>
            fp <span className="font-data-mono">{p.evidence_input_fingerprint || '—'}</span>
          </span>
          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-bold uppercase tracking-wider border ${
            data.stale ? 'bg-red-50 text-red-800 border-red-200' : 'bg-green-50 text-green-800 border-green-200'
          }`}>
            {data.stale ? <AlertTriangle size={12} /> : <CheckCircle size={12} />}
            {data.stale ? 'Stale' : 'Fresh'}
          </span>
        </div>
      </div>

      {/* Stale banner */}
      {data.stale && (
        <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm">
          <b>This report is stale.</b> {data.stale_reason}
        </div>
      )}

      {/* Synthetic-data disclaimer */}
      <div className="bg-[#fffbeb] border border-[#fde68a] text-[#78350f] rounded-xl p-3 text-xs leading-relaxed flex gap-2">
        <ShieldAlert size={15} className="shrink-0 mt-0.5" />
        <span>{p.note}</span>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-[#45464d] mb-1">Overall test WAPE</div>
          <div className="text-xl font-bold font-data-mono text-[#0d1c2d]">{wapePct(s.overall_test_wape)}</div>
          <div className="text-[11px] text-[#76777d] mt-0.5">≈{s.approx_point_accuracy_pct ?? '—'}% intuitive accuracy</div>
        </div>
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-[#45464d] mb-1">XGBoost champions</div>
          <div className="text-xl font-bold font-data-mono text-[#0d1c2d]">
            {data.campaigns.filter((c) => c.is_xgb_champion).length}/{data.campaigns.length}
          </div>
          <div className="text-[11px] text-[#76777d] mt-0.5">{s.fallback_campaigns.length} fall back to baseline</div>
        </div>
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-[#45464d] mb-1">Holdout drift</div>
          <div className={`text-xl font-bold font-data-mono ${s.champion_holdout_drift_campaigns.length ? 'text-amber-600' : 'text-[#0d1c2d]'}`}>
            {s.champion_holdout_drift_campaigns.length}
          </div>
          <div className="text-[11px] text-[#76777d] mt-0.5">flagged for retraining</div>
        </div>
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-4 shadow-sm">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-[#45464d] mb-1">Evidence safety</div>
          <div className="text-sm font-bold text-[#0d1c2d] mt-1 space-y-0.5">
            <div className="flex items-center gap-1"
                 title={s.safe_for_model_demo ? 'Champion held up on the untouched test window' : 'Champion regressed on the untouched test — flagged for retraining'}>
              {s.safe_for_model_demo ? <CheckCircle size={12} className="text-green-600" /> : <AlertTriangle size={12} className="text-amber-500" />} Model evidence
            </div>
            <div className="flex items-center gap-1"
                 title={s.safe_for_decision_demo ? 'Selection evidence is safe to lean on for decisions' : 'Drift/regression flagged — not safe to lean on for decisions (retrain first)'}>
              {s.safe_for_decision_demo ? <CheckCircle size={12} className="text-green-600" /> : <AlertTriangle size={12} className="text-amber-500" />} Decision use
            </div>
          </div>
        </div>
      </div>

      {/* Campaign selector */}
      <div className="flex flex-wrap gap-2">
        {data.campaigns.map((c) => {
          const active = c.campaign_id === selected.campaign_id;
          return (
            <button
              key={c.campaign_id}
              onClick={() => setSelectedId(c.campaign_id)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all flex items-center gap-1.5 ${
                active
                  ? 'bg-[#131b2e] text-white border-[#131b2e]'
                  : 'bg-white text-[#45464d] border-[#c6c6cd]/50 hover:border-[#00714d]/40'
              }`}
            >
              <span className="font-data-mono">{c.campaign_id}</span>
              {c.holdout_drift && <AlertTriangle size={12} className={active ? 'text-amber-300' : 'text-amber-500'} />}
            </button>
          );
        })}
      </div>

      {/* Untouched-test forecast accuracy — the row-level "does it track reality" beat */}
      {data.series_available && selected.test_series.length > 0 && (
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-6 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-2 mb-1">
            <div className="flex items-center gap-2">
              <LineChart size={15} className="text-[#00714d]" />
              <h3 className="text-sm font-bold text-[#0d1c2d]">
                Untouched-test forecast accuracy — {selected.campaign_id}
              </h3>
            </div>
            <div className="text-[11px] text-[#76777d]">
              {selected.test_series.length} holdout days · champion WAPE{' '}
              <span className="font-data-mono font-semibold text-[#0d1c2d]">{wapePct(selected.champion_test_wape)}</span>
              {selected.test_coverage !== null && (
                <> · band coverage <span className="font-data-mono font-semibold text-[#0d1c2d]">{wapePct(selected.test_coverage)}</span></>
              )}
            </div>
          </div>
          <p className="text-[11px] text-[#76777d] mb-2">
            Every point is a real holdout label scored <b>after</b> selection — the same rows the WAPE bars summarize.
            P50 is the deployed champion forecast; the band is conformal (XGBoost) or the ±20% baseline heuristic.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-[1.7fr_1fr] gap-5">
            <div className="flex flex-col h-[260px]">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-[#45464d]">Forecast vs actual over time</span>
              <ForecastFanChart series={selected.test_series} />
            </div>
            <div className="flex flex-col h-[260px]">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-[#45464d]">Actual vs predicted</span>
              <ActualVsPredictedChart series={selected.test_series} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-4 mt-3 pt-3 border-t border-[#e2e8f0]/50 text-[10px] font-semibold text-[#45464d]">
            <span className="flex items-center gap-1.5"><span className="w-3 h-[2px] bg-[#006c49] inline-block" /> P50 (champion)</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-[#3bc6c2]/30 border border-[#3bc6c2] inline-block" /> P10–P90 band</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-[#0d1c2d] inline-block" /> actual (in band)</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-[#ba1a1a] inline-block" /> actual (outside)</span>
          </div>
        </div>
      )}

      {/* Champion Selection — pre-test selection vs untouched test (kept strictly separate) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pre-test selection evidence (frozen folds) */}
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-1">
            <FlaskConical size={15} className="text-[#00714d]" />
            <h3 className="text-sm font-bold text-[#0d1c2d]">Pre-test selection (frozen folds)</h3>
          </div>
          <p className="text-[11px] text-[#76777d] mb-4">
            The decision that PICKED the champion — made only on pre-test rolling folds. The test window below was never used here.
          </p>

          {pre ? (
            <>
              <div className="space-y-3 mb-4">
                <WapeBar label="XGBoost (candidate)" wape={pre.xgb_wape} max={preMax} winner={xgbWinsPre} />
                <WapeBar label="Best baseline" wape={pre.best_baseline_wape} max={preMax} winner={!xgbWinsPre} />
              </div>
              <p className="text-[10px] text-[#76777d] mb-4 italic">
                Only two bars are persisted: the XGBoost candidate and the winning baseline. Per-baseline pre-test scores are not stored.
              </p>
              <div className="grid grid-cols-3 gap-3 text-center border-t border-[#e2e8f0]/60 pt-3">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-semibold">Improvement</div>
                  <div className={`text-base font-bold font-data-mono ${pre.improvement_pct >= 0 ? 'text-[#00714d]' : 'text-red-600'}`}>
                    {pre.improvement_pct >= 0 ? '+' : ''}{pre.improvement_pct.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-semibold">Fold wins</div>
                  <div className="text-base font-bold font-data-mono text-[#0d1c2d]">{pre.fold_wins}/{pre.n_folds}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-semibold">Threshold</div>
                  <div className="text-base font-bold font-data-mono text-[#0d1c2d]">{(pre.threshold * 100).toFixed(0)}%</div>
                </div>
              </div>
              <div className="mt-4 bg-[#f8f9ff] border border-[#e2e8f0] rounded-lg p-3">
                <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-semibold mb-1">Selector reason</div>
                <p className="text-xs text-[#0d1c2d] font-data-mono leading-relaxed">{pre.reason}</p>
              </div>
            </>
          ) : (
            <div className="text-xs text-[#45464d] bg-[#f8f9ff] border border-[#e2e8f0] rounded-lg p-4">
              No XGBoost promotion evidence recorded for this campaign — the frozen selector kept the{' '}
              <span className="font-data-mono">{modelLabel(selected.selected_model)}</span> baseline as champion
              (XGBoost did not clear the promotion threshold on pre-test folds).
            </div>
          )}
        </div>

        {/* Untouched-test panel — never used for selection */}
        <div className={`bg-white border rounded-xl p-6 shadow-sm ${selected.holdout_drift ? 'border-amber-200' : 'border-[#e2e8f0]'}`}>
          <div className="flex items-center justify-between gap-2 mb-1">
            <div className="flex items-center gap-2">
              <Trophy size={15} className="text-[#b45309]" />
              <h3 className="text-sm font-bold text-[#0d1c2d]">Untouched test — never used for selection</h3>
            </div>
            {selected.holdout_drift && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border bg-amber-50 text-amber-800 border-amber-200">
                <AlertTriangle size={11} /> Holdout drift
              </span>
            )}
          </div>
          <p className="text-[11px] text-[#76777d] mb-4">
            All three models scored on the held-out test window, AFTER selection. This is an audit of the champion, not a re-selection.
          </p>

          <div className="space-y-3 mb-4">
            {selected.test_points.map((t) => {
              const isChampion =
                (selected.is_xgb_champion && t.model === 'xgboost_p50') ||
                (!selected.is_xgb_champion && t.model === selected.selected_model);
              return (
                <div key={t.model}>
                  <WapeBar
                    label={modelLabel(t.model)}
                    wape={t.wape}
                    max={testMax}
                    champion={isChampion}
                    drift={isChampion && selected.holdout_drift}
                    winner={!isChampion && t.wape !== null && t.wape === Math.min(...selected.test_points.map((x) => x.wape ?? Infinity))}
                  />
                </div>
              );
            })}
          </div>

          {selected.holdout_drift ? (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-[#78350f] leading-relaxed">
              <b>Champion regressed on the untouched test</b> — {selected.drift_pct_worse?.toFixed(0)}% worse WAPE than the
              best baseline ({wapePct(selected.champion_test_wape)} vs {wapePct(selected.best_baseline_test_wape)}). It is
              surfaced as a <b>retraining signal</b> and deliberately <b>NOT</b> switched: flipping the champion on test
              results would leak the test set into the selection policy.
            </div>
          ) : (
            <div className="bg-[#f8f9ff] border border-[#e2e8f0] rounded-lg p-3 text-xs text-[#45464d] leading-relaxed">
              The champion held up on the untouched test ({wapePct(selected.champion_test_wape)} vs best baseline{' '}
              {wapePct(selected.best_baseline_test_wape)}) — no material holdout drift.
            </div>
          )}
        </div>
      </div>

      {/* Lead walkthrough note */}
      {selected.campaign_id === LEAD_CAMPAIGN && selected.holdout_drift && (
        <div className="bg-[#131b2e] text-[#dae2fd] rounded-xl p-5 text-sm leading-relaxed">
          <span className="text-xs uppercase tracking-wider font-semibold text-white">Walkthrough · {humanize(selected.campaign_id)}</span>
          <p className="mt-2">
            Google PMax was <b>promoted to XGBoost on pre-test evidence</b> (beat the best baseline by{' '}
            {pre?.improvement_pct.toFixed(1)}% WAPE, won {pre?.fold_wins}/{pre?.n_folds} folds). On the untouched test it then{' '}
            <b>regressed</b> ({wapePct(selected.champion_test_wape)} vs {wapePct(selected.best_baseline_test_wape)} baseline). The
            engine flags it for retraining but does <b>not</b> retroactively switch the champion — that separation is exactly
            what keeps the selection honest.
          </p>
        </div>
      )}
    </div>
  );
}

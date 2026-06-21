import {
  RefreshCw,
  RotateCcw,
  CheckCheck,
  Loader2,
} from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';

export default function Header() {
  const { rec, decision, loading, solving, busy, decided, dirty, approveBlockedReason, recompute, resetAll, decide } =
    useRecommendation();

  const handleResetAll = () => {
    if (
      window.confirm(
        'Reset demo state?\n\nThis clears the durable decision ledger and all SKU approvals, ' +
          'returning the app to a fresh, pre-decision state. (A recorded approval is normally ' +
          'immutable — this is a demo reset, not an un-approve.)',
      )
    ) {
      void resetAll();
    }
  };

  const recalculating = loading || solving;
  // `dirty` is true while solving OR when staged edits haven't been applied yet.
  // Show the green Recompute affordance whenever the plan is out of sync; only
  // allow a click once the current solve has settled.
  const showRecompute = dirty && !decided;
  const canRecompute = showRecompute && !solving;
  const approved = decision?.status === 'approved';
  const approveDisabled = busy || decided || approveBlockedReason !== null || !rec;

  return (
    <header className="h-14 bg-white border-b border-[#e2e8f0] sticky top-0 z-20 flex justify-between items-center px-8 select-none">
      {/* Action Buttons & Profile controls */}
      <div className="flex items-center gap-5 ml-auto">
        {/* Dynamic Action Buttons */}
        <div className="flex items-center gap-2.5">
          <button
            onClick={handleResetAll}
            disabled={busy || recalculating}
            title="Demo reset: clear the decision ledger + SKU approvals and start fresh"
            className={`px-3 py-1.5 border text-xs font-semibold rounded-lg flex items-center gap-1.5 transition-all ${
              decided
                ? 'border-[#fca5a5] text-[#b91c1c] hover:bg-[#fef2f2] active:scale-95'
                : 'border-[#c6c6cd] text-[#45464d] hover:bg-[#f8f9ff] active:scale-95'
            } ${busy || recalculating ? 'opacity-60 cursor-not-allowed' : ''}`}
          >
            <RotateCcw size={13} className={decided ? 'text-[#b91c1c]' : 'text-[#76777d]'} />
            <span>Reset</span>
          </button>

          <button
            onClick={recompute}
            disabled={!canRecompute}
            title={
              showRecompute
                ? 'Recompute the plan from your edited constraints'
                : 'Plan is up to date with your inputs — edit constraints in Budget Planner to enable'
            }
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg focus:outline-none flex items-center gap-1.5 transition-all ${
              showRecompute
                ? `bg-[#00714d] text-white shadow-sm hover:bg-[#005c3f] ${canRecompute ? 'active:scale-95' : 'opacity-80 cursor-wait'}`
                : 'border border-[#c6c6cd] text-[#76777d] opacity-60 cursor-not-allowed'
            }`}
          >
            {solving ? (
              <Loader2 size={13} className="animate-spin text-white" />
            ) : (
              <RefreshCw size={13} className={showRecompute ? 'text-white' : 'text-[#76777d]'} />
            )}
            <span>{solving ? 'Recomputing…' : 'Recompute'}</span>
          </button>

          <button
            onClick={() => decide('approve')}
            disabled={approveDisabled}
            title={approved ? 'Recorded to the append-only audit ledger' : approveBlockedReason ?? 'Approve this plan'}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg text-white shadow-sm flex items-center gap-1.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
              approved
                ? 'bg-[#00714d] cursor-default'
                : 'bg-[#131b2e] hover:bg-[#233143] active:scale-95'
            }`}
          >
            {approved ? (
              <>
                <CheckCheck size={13} />
                <span>Plan Recorded</span>
              </>
            ) : (
              <span>Approve Plan</span>
            )}
          </button>
        </div>

        {/* User profile */}
        <div className="w-8 h-8 rounded-full bg-[#d4e4fa] overflow-hidden border border-[#c6c6cd] shrink-0 flex items-center justify-center text-[#0d1c2d] text-xs font-bold">
          YP
        </div>
      </div>
    </header>
  );
}

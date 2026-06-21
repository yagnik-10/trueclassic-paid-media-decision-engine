import React, { useState } from 'react';
import { X, Sparkles, Calculator } from 'lucide-react';
import { useRecommendation, type Policy } from '../state/RecommendationContext';
import type { ReserveMode } from '../lib/api';

interface NewOptimizationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onApplied: () => void;
}

export default function NewOptimizationModal({ isOpen, onClose, onApplied }: NewOptimizationModalProps) {
  const { cons, applyScenario } = useRecommendation();
  const [policy, setPolicy] = useState<Policy>('expected');
  const [floor, setFloor] = useState<number>(cons?.roas_floor ?? 4.0);
  const [reserve, setReserve] = useState<ReserveMode>(cons?.reserve_mode ?? 'growth');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Drives the real optimizer through the shared state layer — one recompute.
    applyScenario(policy, { roas_floor: floor, reserve_mode: reserve });
    onApplied();
  };

  return (
    <div className="fixed inset-0 bg-[#131b2e]/60 backdrop-blur-xs flex items-center justify-center z-50 animate-fade-in p-4 select-none">
      <div className="bg-white rounded-xl max-w-xl w-full flex flex-col shadow-2xl border border-[#e2e8f0] overflow-hidden">
        <div className="p-4 border-b border-[#e2e8f0] flex justify-between items-center bg-[#f8f9ff]">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-[#00714d]" />
            <span className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">Configure New Optimization</span>
          </div>
          <button onClick={onClose} className="text-[#76777d] hover:text-[#0d1c2d] p-1 rounded-full hover:bg-gray-100 transition-colors">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5 text-xs text-[#0d1c2d]">
          {/* Policy */}
          <div className="space-y-2">
            <span className="font-bold text-[#45464d] uppercase tracking-wider block">Risk Policy</span>
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setPolicy('expected')}
                      className={`p-3 rounded-lg border text-left flex flex-col gap-1 transition-all ${policy === 'expected' ? 'border-[#00714d] bg-[#e6fffa]/20 shadow-sm' : 'border-[#e2e8f0] hover:bg-[#eef4ff]'}`}>
                <span className="font-semibold text-xs">Expected</span>
                <span className="text-[10px] text-[#76777d] leading-normal font-normal">Point-estimate marginals; risk-adjusted growth.</span>
              </button>
              <button type="button" onClick={() => setPolicy('conservative')}
                      className={`p-3 rounded-lg border text-left flex flex-col gap-1 transition-all ${policy === 'conservative' ? 'border-[#00714d] bg-[#e6fffa]/20 shadow-sm' : 'border-[#e2e8f0] hover:bg-[#eef4ff]'}`}>
                <span className="font-semibold text-xs">Conservative</span>
                <span className="text-[10px] text-[#76777d] leading-normal font-normal">Downside marginals; tighter movement bounds.</span>
              </button>
            </div>
          </div>

          {/* ROAS floor + reserve mode */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="font-bold text-[#45464d] uppercase tracking-wider block">Calibrated ROAS Floor</label>
              <div className="flex items-center gap-2">
                <input type="range" min={2} max={8} step={0.1} value={floor}
                       onChange={(e) => setFloor(parseFloat(e.target.value))}
                       className="w-full h-1 bg-[#dae2fd] rounded appearance-none cursor-pointer accent-[#131b2e]" />
                <span className="font-bold font-data-mono shrink-0 w-10 text-right text-xs">{floor.toFixed(1)}×</span>
              </div>
              <p className="text-[10px] text-[#76777d]">Enforced governance floor (gross calibrated ROAS).</p>
            </div>

            <div className="space-y-1.5">
              <label className="font-bold text-[#45464d] uppercase tracking-wider block">Reserve Mode</label>
              <div className="grid grid-cols-2 gap-1.5 bg-[#eef4ff] p-1 rounded-lg border border-[#c6c6cd]/20">
                {(['growth', 'efficiency_first'] as const).map((m) => (
                  <button key={m} type="button" onClick={() => setReserve(m)}
                          className={`py-1.5 text-[11px] font-semibold rounded-md transition-colors ${reserve === m ? 'bg-white text-[#0d1c2d] shadow-sm' : 'text-[#45464d]'}`}>
                    {m === 'growth' ? 'Growth' : 'Efficiency'}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-[#76777d]">Hold budget in reserve below the per-dollar hurdle.</p>
            </div>
          </div>

          <p className="text-[10px] text-[#76777d] bg-[#f8f9ff] border border-[#e2e8f0] rounded-lg p-2.5 leading-relaxed">
            Scope is Meta + Google. Total spend is an optimizer output bounded by the per-campaign movement limit — there is no
            settable budget pool. Fine-grained NC-CPA / prospecting / movement controls live in the Budget Planner.
          </p>

          <div className="pt-4 border-t border-[#e2e8f0] flex justify-end gap-2.5">
            <button type="button" onClick={onClose}
                    className="px-4 py-2 border border-[#c6c6cd] font-semibold rounded-lg hover:bg-[#f8f9ff] text-[#45464d] transition-colors">
              Cancel
            </button>
            <button type="submit"
                    className="px-5 py-2 hover:opacity-95 font-semibold bg-[#131b2e] text-white rounded-lg flex items-center gap-1.5 transition-all shadow-sm active:scale-95">
              <Calculator size={13} />
              <span>Build Optimization</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

import { 
  LayoutDashboard, 
  Database, 
  TrendingUp, 
  Coins, 
  Package,
  Microscope,
  Gavel,
} from 'lucide-react';
import { ActiveTab } from '../types';
import { TrueClassicWordmark } from './BrandLogo';
import { useRecommendation } from '../state/RecommendationContext';

interface SidebarProps {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
}

export default function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
  const { rec, loading, solving, error } = useRecommendation();

  // Honest, live engine status — no fabricated "system health". Reflects the
  // backend connection and the active scenario's feasibility.
  const status: { dot: string; text: string; label: string } = error && !rec
    ? { dot: 'bg-red-500', text: 'text-[#b91c1c]', label: 'Engine offline' }
    : loading || solving || !rec
      ? { dot: 'bg-amber-400 animate-pulse', text: 'text-[#b45309]', label: solving ? 'Solving…' : 'Connecting…' }
      : rec.feasible
        ? { dot: 'bg-[#006c49]', text: 'text-[#00714d]', label: 'Engine online · feasible' }
        : { dot: 'bg-red-500', text: 'text-[#b91c1c]', label: 'Engine online · infeasible' };

  const menuItems = [
    {
      id: ActiveTab.Overview,
      label: 'Decision Overview',
      icon: LayoutDashboard,
    },
    {
      id: ActiveTab.DataUnification,
      label: 'Data Unification',
      icon: Database,
    },
    {
      id: ActiveTab.ForecastResponse,
      label: 'Forecast & Response',
      icon: TrendingUp,
    },
    {
      id: ActiveTab.BudgetPlanner,
      label: 'Budget Planner',
      icon: Coins,
    },
    {
      id: ActiveTab.BuyerInventory,
      label: 'Buyer & Inventory',
      icon: Package,
    },
    {
      id: ActiveTab.ModelEvidence,
      label: 'Model Evidence',
      icon: Microscope,
    },
    {
      id: ActiveTab.AuditControls,
      label: 'Audit & Business Controls',
      icon: Gavel,
    },
  ];

  return (
    <aside className="w-64 bg-white border-r border-[#e2e8f0] flex flex-col h-screen fixed left-0 top-0 z-30 select-none">
      {/* Brand Header */}
      <div className="p-6 border-b border-[#e2e8f0]/40">
        <div className="flex flex-col items-center gap-2">
          <TrueClassicWordmark className="h-5" />
          <p className="text-[10px] text-[#00714d] font-bold tracking-[0.12em] uppercase text-center">
            Media Decision &amp; Governance
          </p>
        </div>
      </div>

      {/* Main Navigation Tab list */}
      <nav className="flex-1 py-6 overflow-y-auto px-4 space-y-1">
        {menuItems.map((item) => {
          const IconComponent = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 text-left group ${
                isActive
                  ? 'bg-[#e5efff] text-[#00714d] font-semibold font-label-md'
                  : 'text-[#45464d] hover:bg-[#eef4ff] hover:text-[#0d1c2d]'
              }`}
            >
              <IconComponent
                size={18}
                className={`transition-colors flex-shrink-0 ${
                  isActive ? 'text-[#00714d]' : 'text-[#76777d] group-hover:text-[#0d1c2d]'
                }`}
              />
              <span className="font-medium text-xs leading-none">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Live engine status */}
      <div className="px-5 py-3 border-t border-[#e2e8f0]/50 bg-[#f8f9ff]">
        <div className="flex items-center gap-2" title={status.label}>
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${status.dot}`} />
          <span className={`text-[10px] font-semibold font-data-mono truncate ${status.text}`}>
            {status.label}
          </span>
        </div>
      </div>
    </aside>
  );
}

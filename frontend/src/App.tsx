import { useState } from 'react';
import { ActiveTab } from './types';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import DecisionOverview from './components/DecisionOverview';
import DataUnification from './components/DataUnification';
import ForecastResponse from './components/ForecastResponse';
import BudgetPlanner from './components/BudgetPlanner';
import BuyerInventory from './components/BuyerInventory';
import ModelEvidence from './components/ModelEvidence';
import AuditControls from './components/AuditControls';
import NewOptimizationModal from './components/NewOptimizationModal';

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>(ActiveTab.Overview);
  const [isOpenNewModal, setIsOpenNewModal] = useState(false);

  // Each workspace is self-contained: it reads/writes the live engine through
  // RecommendationContext, so App only owns navigation + the optimization modal.
  const renderActiveTabContent = () => {
    switch (activeTab) {
      case ActiveTab.Overview:
        return <DecisionOverview onNavigateToTab={(tab) => setActiveTab(tab)} />;
      case ActiveTab.DataUnification:
        return <DataUnification />;
      case ActiveTab.ForecastResponse:
        return <ForecastResponse />;
      case ActiveTab.BudgetPlanner:
        return <BudgetPlanner />;
      case ActiveTab.BuyerInventory:
        return <BuyerInventory />;
      case ActiveTab.ModelEvidence:
        return <ModelEvidence />;
      case ActiveTab.AuditControls:
        return <AuditControls />;
      default:
        return <div>Tab not implemented</div>;
    }
  };

  return (
    <div className="bg-[#f8f9ff] text-[#0d1c2d] min-h-screen flex antialiased font-sans transition-all">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onOpenNewOptimization={() => setIsOpenNewModal(true)}
      />

      <div className="flex-1 md:ml-64 flex flex-col min-h-screen">
        <Header />

        <main className="flex-1 p-8 overflow-y-auto bg-[#f8f9ff]">
          <div className="max-w-[1440px] mx-auto pb-12">
            {renderActiveTabContent()}
          </div>
        </main>
      </div>

      <NewOptimizationModal
        isOpen={isOpenNewModal}
        onClose={() => setIsOpenNewModal(false)}
        onApplied={() => {
          setIsOpenNewModal(false);
          setActiveTab(ActiveTab.Overview);
        }}
      />
    </div>
  );
}

// UI-only domain types. Engine/API data shapes live in `src/lib/api.ts`; this
// file holds just the front-end navigation model.
export enum ActiveTab {
  Overview = 'overview',
  DataUnification = 'data-unification',
  ForecastResponse = 'forecast-response',
  BudgetPlanner = 'budget-planner',
  BuyerInventory = 'buyer-inventory',
  ModelEvidence = 'model-evidence',
  AuditControls = 'audit-controls'
}

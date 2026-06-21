import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  getAudit,
  getRecommendation,
  postDecision,
  resetDemoState,
  type ConstraintParams,
  type DecisionResponse,
  type Recommendation,
} from "../lib/api";

export type Policy = "expected" | "conservative";

// The single active-scenario state for the whole app. Every page reads the same
// recommendation; no page keeps its own mock copy. The backend response is the
// only source of truth — KPIs are never recomputed in the browser.
interface RecommendationState {
  rec: Recommendation | null;
  decision: DecisionResponse | null;
  policy: Policy;
  cons: ConstraintParams | null; // the draft constraints bound to the inputs
  loading: boolean; // first load
  solving: boolean; // a recalculation is in flight
  busy: boolean; // an approve/reject is in flight
  error: string | null;
  decided: boolean;
  dirty: boolean; // inputs differ from the solved/displayed plan
  approveBlockedReason: string | null; // null ⇒ approval is allowed
  setPolicy: (p: Policy) => void;
  update: (patch: Partial<ConstraintParams>) => void;
  // Draft editing: stage constraint/policy edits WITHOUT solving, then `recompute`
  // runs the optimizer once for the whole batch (Budget Planner apply step).
  updateDraft: (patch: Partial<ConstraintParams>) => void;
  setPolicyDraft: (p: Policy) => void;
  recompute: () => void;
  applyScenario: (p: Policy, patch: Partial<ConstraintParams>) => void;
  reset: () => void;
  resetAll: () => Promise<void>;
  decide: (action: "approve" | "reject", notes?: string) => Promise<void>;
}

const Ctx = createContext<RecommendationState | null>(null);

const APPROVER = "marketer@trueclassic";

export function RecommendationProvider({ children }: { children: ReactNode }) {
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [policy, setPolicyState] = useState<Policy>("expected");
  const [cons, setCons] = useState<ConstraintParams | null>(null);
  const [loading, setLoading] = useState(true);
  const [solving, setSolving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Seed the form from the BACKEND's own defaults (no constraints sent), so the
  // UI never hard-codes policy values that could drift from config.py.
  const loadDefaults = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getRecommendation("expected");
      setRec(r);
      setCons(r.constraints);
      setPolicyState("expected");
      setDecision(r.status !== "pending" ? await getAudit(r.scenario_id) : null);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDefaults();
  }, [loadDefaults]);

  const reload = useCallback((p: Policy, c: ConstraintParams) => {
    if (timer.current) clearTimeout(timer.current);
    setSolving(true);
    timer.current = setTimeout(async () => {
      try {
        setRec(await getRecommendation(p, c));
        setError(null);
      } catch (e: any) {
        setError(e?.message ?? String(e));
      } finally {
        setSolving(false);
      }
    }, 250);
  }, []);

  const update = useCallback(
    (patch: Partial<ConstraintParams>) => {
      setCons((prev) => {
        const base = prev ?? rec?.constraints;
        if (!base) return prev;
        const next = { ...base, ...patch };
        reload(policy, next);
        return next;
      });
    },
    [policy, rec, reload],
  );

  const setPolicy = useCallback(
    (p: Policy) => {
      setPolicyState(p);
      if (cons) reload(p, cons);
    },
    [cons, reload],
  );

  // --- Draft editing (no solve until `recompute`) --------------------------
  const updateDraft = useCallback(
    (patch: Partial<ConstraintParams>) => {
      setCons((prev) => {
        const base = prev ?? rec?.constraints;
        if (!base) return prev;
        return { ...base, ...patch };
      });
    },
    [rec],
  );

  const setPolicyDraft = useCallback((p: Policy) => setPolicyState(p), []);

  const recompute = useCallback(() => {
    if (cons) reload(policy, cons);
  }, [cons, policy, reload]);

  // Set policy AND constraints together, then recompute once (used by the New
  // Optimization modal so the two changes don't race two separate reloads).
  const applyScenario = useCallback(
    (p: Policy, patch: Partial<ConstraintParams>) => {
      setPolicyState(p);
      setCons((prev) => {
        const base = prev ?? rec?.constraints;
        if (!base) return prev;
        const next = { ...base, ...patch };
        reload(p, next);
        return next;
      });
    },
    [rec, reload],
  );

  const reset = useCallback(() => {
    setError(null);
    void loadDefaults();
  }, [loadDefaults]);

  // DEMO/admin reset: wipe the backend ledger + SKU approvals, then reload the fresh
  // (now-pending) defaults so the whole app returns to a clean, pre-decision slate.
  const resetAll = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await resetDemoState();
      setDecision(null);
      await loadDefaults();
    } catch (e: any) {
      const prefix = e instanceof ApiError ? `(${e.status}) ` : "";
      setError(prefix + (e?.message ?? String(e)));
    } finally {
      setBusy(false);
    }
  }, [loadDefaults]);

  const decide = useCallback(
    async (action: "approve" | "reject", notes?: string) => {
      if (!rec) return;
      setBusy(true);
      setError(null);
      try {
        // bind to the displayed snapshot by scenario_id — no re-solve
        setDecision(await postDecision(rec.scenario_id, action, APPROVER, notes));
      } catch (e: any) {
        // 409 stale/superseded and 422 infeasible/sensitivity arrive here as ApiError
        const prefix = e instanceof ApiError ? `(${e.status}) ` : "";
        setError(prefix + (e?.message ?? String(e)));
      } finally {
        setBusy(false);
      }
    },
    [rec],
  );

  const decided = !!decision;

  // The displayed plan is "dirty" while re-solving or when the inputs no longer
  // match what's shown — approval is disabled until the exact plan is recomputed.
  const dirty = useMemo(() => {
    if (!rec || !cons) return false;
    return (
      solving ||
      policy !== rec.policy_mode ||
      JSON.stringify(cons) !== JSON.stringify(rec.constraints)
    );
  }, [rec, cons, solving, policy]);

  // Mirror the backend's approval gates exactly (backend/api/main.py::decide).
  const approveBlockedReason = useMemo(() => {
    if (!rec) return "Loading…";
    if (decided) return null;
    if (busy) return "Decision in progress…";
    if (dirty) return "Inputs changed — recompute before deciding.";
    if (!rec.feasible) return "Plan is infeasible and cannot be approved.";
    if (rec.is_sensitivity_override)
      return "Sensitivity scenario (non-registry-approved calibration) cannot be approved.";
    return null;
  }, [rec, decided, busy, dirty]);

  const value: RecommendationState = {
    rec,
    decision,
    policy,
    cons,
    loading,
    solving,
    busy,
    error,
    decided,
    dirty,
    approveBlockedReason,
    setPolicy,
    update,
    updateDraft,
    setPolicyDraft,
    recompute,
    applyScenario,
    reset,
    resetAll,
    decide,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRecommendation(): RecommendationState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRecommendation must be used within RecommendationProvider");
  return ctx;
}

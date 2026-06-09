import type React from "react";
import { createContext, type ReactNode, useContext, useEffect, useReducer } from "react";
import type { AgentOutput } from "@/types/agents";
import type { Hypothesis } from "@/types/hypothesis";
import type { GenerationState } from "@/types/workflow";
import { loadLastRunState, saveLastRunState } from "@/utils/statePersistence";

// Initial state
const initialState: GenerationState = {
  status: "idle",
  taskId: null,
  researchGoal: "",
  progress: 0,
  progressMessage: "",
  agentOutputs: [],
  hypotheses: [],
  researchPlan: null,
  metaReview: null,
  tournamentMatchups: [],
  evolutionDetails: [],
  similarityClusters: [],
  currentIteration: 0,
  maxIterations: 0,
  executionTime: 0,
  metrics: {},
  error: null,
};

// Action types
type GenerationAction =
  | {
      type: "START_GENERATION";
      payload: { taskId: string; researchGoal: string; maxIterations: number };
    }
  | { type: "UPDATE_PROGRESS"; payload: { progress: number; message: string } }
  | { type: "ADD_AGENT_OUTPUT"; payload: AgentOutput }
  | {
      type: "UPDATE_STATE";
      payload: Partial<Omit<GenerationState, "status" | "error">>;
    }
  | {
      type: "COMPLETE";
      payload?: {
        hypotheses?: Hypothesis[];
        researchPlan?: object;
        metaReview?: object;
        tournamentMatchups?: object[];
        evolutionDetails?: object[];
        similarityClusters?: object[];
        executionTime?: number;
        metrics?: object;
      };
    }
  | { type: "ERROR"; payload: string }
  | { type: "CANCELLING" }
  | { type: "CANCEL" }
  | { type: "RESET" }
  | { type: "RESTORE_STATE"; payload: GenerationState };

// Reducer
function generationReducer(state: GenerationState, action: GenerationAction): GenerationState {
  switch (action.type) {
    case "START_GENERATION":
      return {
        ...initialState,
        status: "generating",
        taskId: action.payload.taskId,
        researchGoal: action.payload.researchGoal,
        maxIterations: action.payload.maxIterations,
      };

    case "UPDATE_PROGRESS":
      return {
        ...state,
        progress: action.payload.progress,
        progressMessage: action.payload.message,
      };

    case "ADD_AGENT_OUTPUT": {
      // Deduplicate: For review nodes, check if we already have this hypothesis review
      const newOutput = action.payload;

      if (newOutput.name === "HypothesisReflector" && newOutput.parsed?.hypothesis_text) {
        // Check if we already have a review for this hypothesis in this iteration
        const isDuplicate = state.agentOutputs.some(
          (existing) =>
            existing.name === "HypothesisReflector" &&
            existing.parsed?.hypothesis_text === newOutput.parsed?.hypothesis_text &&
            existing.iteration === newOutput.iteration
        );

        if (isDuplicate) {
          // Skip adding duplicate review
          return state;
        }
      }

      return {
        ...state,
        agentOutputs: [...state.agentOutputs, newOutput],
      };
    }

    case "UPDATE_STATE":
      return {
        ...state,
        ...action.payload,
      };

    case "COMPLETE":
      return {
        ...state,
        status: "completed",
        hypotheses: action.payload?.hypotheses || state.hypotheses,
        researchPlan: action.payload?.researchPlan || state.researchPlan,
        metaReview: action.payload?.metaReview || state.metaReview,
        tournamentMatchups: action.payload?.tournamentMatchups || state.tournamentMatchups,
        evolutionDetails: action.payload?.evolutionDetails || state.evolutionDetails,
        similarityClusters: action.payload?.similarityClusters || state.similarityClusters,
        executionTime: action.payload?.executionTime || state.executionTime,
        metrics: action.payload?.metrics || state.metrics,
      };

    case "ERROR":
      return {
        ...state,
        status: "error",
        error: action.payload,
      };

    case "CANCELLING":
      return {
        ...state,
        status: "cancelling",
      };

    case "CANCEL":
      return {
        ...state,
        status: "cancelled",
      };

    case "RESET":
      return initialState;

    case "RESTORE_STATE":
      // Restore state from file or sessionStorage
      return {
        ...action.payload,
      };

    default:
      return state;
  }
}

// Context
interface GenerationContextValue {
  state: GenerationState;
  dispatch: React.Dispatch<GenerationAction>;
}

const GenerationContext = createContext<GenerationContextValue | undefined>(undefined);

// Provider
export function GenerationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(generationReducer, initialState);

  // Save state to sessionStorage when a run completes
  useEffect(() => {
    if (state.status === "completed") {
      saveLastRunState(state);
    }
  }, [state]);

  // Restore state from sessionStorage on mount (only once)
  useEffect(() => {
    const saved = loadLastRunState();
    if (saved) {
      // Restore the saved state
      dispatch({ type: "RESTORE_STATE", payload: saved });
    }
  }, []); // Empty deps = run once on mount

  return (
    <GenerationContext.Provider value={{ state, dispatch }}>{children}</GenerationContext.Provider>
  );
}

// Custom hook to use the context
export function useGenerationContext() {
  const context = useContext(GenerationContext);
  if (context === undefined) {
    throw new Error("useGenerationContext must be used within a GenerationProvider");
  }
  return context;
}

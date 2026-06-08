import { Hypothesis } from "./hypothesis";

export interface GenerationState {
  status: "idle" | "generating" | "cancelling" | "completed" | "error" | "cancelled";
  taskId: string | null;
  researchGoal: string;
  progress: number;
  progressMessage: string;
  agentOutputs: any[];
  hypotheses: Hypothesis[];
  researchPlan: object | null;
  metaReview: object | null;
  tournamentMatchups: object[];
  evolutionDetails: object[];
  similarityClusters: object[];
  currentIteration: number;
  maxIterations: number;
  executionTime: number;
  metrics: object;
  error: string | null;
}

export interface GenerateRequest {
  research_goal: string;
  model_name?: string;
  max_iterations?: number;
  initial_hypotheses_count?: number;
  evolution_max_count?: number;
  enable_streaming?: boolean;
  enable_literature_review_node?: boolean;
}

export interface GenerateResponse {
  hypotheses: Hypothesis[];
  meta_review: object;
  research_plan: object;
  tournament_matchups: object[];
  evolution_details: object[];
  execution_time: number;
  metrics: object;
}

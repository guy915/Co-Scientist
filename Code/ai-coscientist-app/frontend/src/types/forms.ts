export interface GenerateFormData {
  research_goal: string;
  model_name?: string;
  max_iterations?: number;
  initial_hypotheses_count?: number;
  evolution_max_count?: number;
  enable_streaming?: boolean;
  enable_literature_review_node?: boolean;
}

/** Lifecycle state of a run as reported by the backend. */
export type RunStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'synthesizing'
  | 'completed'
  | 'failed'
  | 'blocked'
  | 'cancelled';

/** Canonical run mode for the single clone workflow. */
export type RunMode = 'default';

/** Former generation profile labels still accepted by the backend. */
export type LegacyRunProfile = RunMode | 'standard' | 'advanced';

/** Research style selected in the Co-Scientist setup flow. */
export type RunFocus =
  | 'prefer_evidence'
  | 'balance'
  | 'prefer_novelty'
  | 'breakthrough';

/** Depth preset selected in the Co-Scientist setup flow. */
export type RunTier = 'express' | 'standard' | 'extended' | 'ultra';

/** Durable setup payload persisted inside `Run.config.setup`. */
export interface RunSetupConfig {
  goal: string;
  requirements: string[];
  attributes: string[];
  criteria: string[];
  focus: RunFocus;
  tier: RunTier;
}

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  | JsonPrimitive
  | JsonValue[]
  | {[key: string]: JsonValue};

/** Typed run configuration JSON stored by the backend. */
export interface RunConfig {
  initial_hypotheses_count?: number;
  max_iterations?: number;
  evolution_max_count?: number;
  tournament_pairs?: number;
  evidence_count?: number;
  literature_review_papers_count?: number;
  enable_literature_review?: boolean;
  k_factor?: number;
  tier?: RunTier;
  focus?: RunFocus;
  setup?: RunSetupConfig;
  [key: string]: JsonValue | RunSetupConfig | undefined;
}

/** A hypothesis-generation run with its goal, config, and current status. */
export interface Run {
  id: string;
  research_goal: string;
  run_mode?: RunMode;
  profile: LegacyRunProfile;
  status: RunStatus;
  provider: 'mock' | 'engine';
  config: RunConfig;
  is_demo?: boolean;
  created_at: number;
  updated_at: number;
  completed_at: number | null;
  error: string | null;
  /**
   * Highest Elo across the run's hypotheses, served by the run-list endpoint so
   * home surfaces avoid fetching hypotheses. Absent/null until the run has any.
   */
  top_elo?: number | null;
}

/** Aggregate counts of the artifacts a run has produced. */
export interface RunSummary {
  events: number;
  hypotheses: number;
  evidence: number;
  matches: number;
  reviews: number;
}

/** A run enriched with its aggregate artifact counts. */
export interface RunWithSummary extends Run {
  summary: RunSummary;
}

/** A generated hypothesis with its scores, lineage, and tournament record. */
export interface Hypothesis {
  id: string;
  run_id: string;
  parent_id: string | null;
  generation: number;
  category: string | null;
  title: string;
  statement: string;
  mechanism: string | null;
  expected_effect: string | null;
  experimental_context: string | null;
  created_by_agent: string;
  created_at: number;
  elo_rating: number;
  win_count: number;
  loss_count: number;
  novelty_score: number | null;
  plausibility_score: number | null;
  testability_score: number | null;
  safety_status: string | null;
  status: string | null;
  cluster_id: string | null;
}

/** A literature record cited as supporting or contextual evidence. */
export interface Evidence {
  id: string;
  title: string;
  source: string;
  url: string;
  authors: string[];
  year: number | null;
  abstract: string;
  available: boolean;
}

/** One pairwise tournament match and the Elo changes it produced. */
export interface MatchRow {
  id: number;
  iteration: number;
  winner_id: string;
  loser_id: string;
  winner_elo_before: number;
  winner_elo_after: number;
  loser_elo_before: number;
  loser_elo_after: number;
  rationale: string;
  tier: string | null;
  created_at: number;
}

/** A reviewer agent's critique and per-axis scores for a hypothesis. */
export interface Review {
  id: number;
  hypothesis_id: string;
  reviewer_agent: string;
  summary: string;
  critique: string;
  novelty: number | null;
  plausibility: number | null;
  testability: number | null;
  overall: number | null;
}

/** A safety-gate decision recorded at a given stage of the pipeline. */
export interface SafetyDecision {
  stage: 'intake' | 'final';
  decision: 'allow' | 'redact' | 'block';
  reason: string;
  matches: string[];
  created_at: number;
}

/** A link between a hypothesis claim and the evidence verifying it. */
export interface CitationRow {
  id: number;
  hypothesis_id: string;
  evidence_id: string;
  claim: string;
  state: 'verified' | 'partial' | 'unsupported' | 'unavailable';
}

/**
 * Structured contents of a run's final synthesis report. One canonical shape
 * for every provider, built server-side by `report_render.build_report_payload`.
 */
export interface ReportPayload {
  research_goal: string;
  run_mode?: RunMode;
  provider: string;
  hypothesis_count?: number;
  evidence_count?: number;
  match_count?: number;
  citation_summary?: Record<string, number>;
  leaderboard: {id: string; title: string; elo: number}[];
  meta_review?: Record<string, unknown>;
  research_overview?: ResearchOverview;
  execution_time?: number;
}

/** Synthesized roadmap and NIH Specific Aims for a run's top hypotheses. */
export interface ResearchOverview {
  overview?: {
    summary?: string;
    research_directions?: {
      title: string;
      importance: string;
      suggested_experiments: string[];
    }[];
  };
  nih_specific_aims?: {
    introduction?: string;
    aims?: {aim: string; rationale: string; approach: string}[];
    impact?: string;
  };
}

/** A persisted run report with its structured payload and markdown path. */
export interface Report {
  id: string;
  run_id: string;
  payload: ReportPayload;
  markdown_path: string;
  created_at: number;
}

/** A cited source attached to a grounded Q&A answer (the `[n]` references). */
export interface SourceRef {
  n: number;
  evidence_id: string;
  title: string;
  url?: string | null;
  source?: string | null;
  year?: number | null;
  state: string;
}

export interface MessageMeta {
  sources?: SourceRef[];
}

/** A chat message exchanged with a run (steering, Q&A, or milestone). */
export interface Message {
  id: number;
  run_id: string;
  sender: 'user' | 'system';
  content: string;
  kind: 'steering' | 'qa' | 'milestone';
  created_at: number;
  applied: boolean;
  status?: string;
  meta?: MessageMeta | null;
}

/** Backend diagnostics describing provider and tool availability. */
export interface SystemStatus {
  mcp_available: boolean;
  pubmed_available: boolean;
  literature_review_available: boolean;
  mcp_server_url: string;
  provider: 'mock' | 'engine';
  mock_mode: boolean;
  has_provider_key: boolean;
  engine_importable: boolean;
  model_name: string;
}

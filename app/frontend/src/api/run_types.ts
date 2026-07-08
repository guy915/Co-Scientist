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

/** A JSON scalar: string, number, boolean, or null. */
export type JsonPrimitive = string | number | boolean | null;
/** Any valid JSON value, recursively defined for arbitrary nesting. */
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
  enable_literature_review?: boolean;
  k_factor?: number;
  tier?: RunTier;
  focus?: RunFocus;
  setup?: RunSetupConfig;
  // RunSetupConfig is included alongside JsonValue because the `setup` key
  // above is typed as RunSetupConfig (not a plain JsonValue); the index
  // signature has to cover every declared property, including that one.
  [key: string]: JsonValue | RunSetupConfig | undefined;
}

/** A hypothesis-generation run with its goal, config, and current status. */
export interface Run {
  id: string;
  research_goal: string;
  run_mode?: RunMode;
  profile: LegacyRunProfile;
  status: RunStatus;
  provider: 'mock' | 'engine'; // which backend produced this run's data
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
  parent_id: string | null; // id of the hypothesis this one evolved from, if any
  generation: number; // 0 for an initial hypothesis, incremented by each evolve pass
  category: string | null;
  title: string;
  statement: string;
  mechanism: string | null;
  expected_effect: string | null;
  experimental_context: string | null;
  created_by_agent: string; // node/agent name that produced it, e.g. "generate", "evolve"
  created_at: number;
  elo_rating: number; // current tournament rating; see app/elo.py
  win_count: number;
  loss_count: number;
  novelty_score: number | null;
  plausibility_score: number | null;
  testability_score: number | null;
  safety_status: string | null; // outcome of the safety screening gate, if run
  status: string | null; // lifecycle state, e.g. active vs. superseded by a later generation
  cluster_id: string | null; // proximity/dedup cluster this hypothesis was grouped into
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
  available: boolean; // whether the full source was reachable when evidence was gathered
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
  tier: string | null; // tournament bracket this match was played in, if tiered
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
  citation_summary?: Record<string, number>; // counts by classification, e.g. verified/partial/unsupported/unavailable
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

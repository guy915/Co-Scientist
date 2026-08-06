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

/** Verified Hypothesis Generation run modes. */
export type RunMode = 'standard' | 'advanced';

/** Former generation profile labels still accepted by the backend. */
export type LegacyRunProfile = RunMode | 'default';

/** Research style selected in the Co-Scientist setup flow. */
export type RunFocus =
  | 'prefer_evidence'
  | 'balance'
  | 'prefer_novelty'
  | 'breakthrough';

/** Depth preset selected in the Co-Scientist setup flow. */
export type RunTier = 'express' | 'standard' | 'extended' | 'ultra';

/**
 * Self-declared audience riding on run, interview, and Q&A requests.
 * Honor system, no server verification.
 */
export type Audience = 'general' | 'google' | 'sbi_ucd';

/** The four verified fields derived by the research-goal interview. */
export interface InterviewFields {
  research_challenge: string;
  focus_area: string[];
  preferences: string[];
  title: string | null;
}

/** One immutable scientist/Agent interview turn. */
export interface InterviewTurn {
  id: number;
  role: 'user' | 'agent';
  content: string;
  /**
   * The Agent's chain of thought for this turn, when the model produced one.
   * Persisted rather than shown and dropped, so a reopened chat replays the
   * thinking the scientist watched arrive.
   */
  reasoning: string | null;
  /**
   * True when the deterministic fallback authored this Agent turn because no
   * model could be reached (no deployment credential and no bring-your-own
   * key answered it). Per turn, so a mid-session credential change marks
   * only the turns it affects; always false for user turns. The timeline
   * renders a quiet notice on marked turns so scripted questions are never
   * silently passed off as model output.
   */
  fallback: boolean;
  created_at: number;
}

/**
 * One entry in the sidebar's chat list: an interview without its transcript,
 * plus the run it started (null until the scientist starts one).
 */
export interface ChatSummary {
  id: string;
  title: string | null;
  challenge: string;
  status: 'active' | 'completed' | 'cancelled';
  run_id: string | null;
  created_at: number;
  updated_at: number;
}

/** Durable interview state returned by the backend. */
export interface Interview {
  id: string;
  client_id: string;
  status: 'active' | 'completed' | 'cancelled';
  fields: InterviewFields;
  current_question: string | null;
  turns: InterviewTurn[];
  created_at: number;
  updated_at: number;
  completed_at: number | null;
}

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
  enable_web_search?: boolean;
  enable_paper_corpus?: boolean;
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
  /**
   * Short model-generated session heading, distinct from the goal (the
   * recents card shows it above the fuller goal). Null until generated shortly
   * after run creation, and for runs created before titles existed; surfaces
   * fall back to a clause of the goal via `firstSentenceClause`.
   */
  title?: string | null;
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
  /**
   * Titles of the run's top hypotheses by Elo, served by the run-list endpoint
   * so home surfaces show real winning ideas without fetching hypotheses.
   * `null` on single-run reads; `[]` for a listed run with no hypotheses yet.
   */
  top_hypotheses?: string[] | null;
  /**
   * The run's most recent pipeline-stage event type (e.g. `generate`,
   * `ranking`), served by the run-list endpoint to drive the live progress
   * indicator. Absent/null on single-run reads and before the first stage.
   */
  latest_stage?: string | null;
  execution_progress?: {
    determinate: boolean;
    completed_tasks: number;
    total_tasks: number;
    fraction: number | null;
    active_task: string | null;
    queued_tasks: number;
  };
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
  // id of the hypothesis this one evolved from, if any
  parent_id: string | null;
  // 0 for an initial hypothesis, incremented by each evolve pass
  generation: number;
  category: string | null;
  title: string;
  statement: string;
  mechanism: string | null;
  expected_effect: string | null;
  experimental_context: string | null;
  // node/agent name that produced it, e.g. "generate", "evolve"
  created_by_agent: string;
  // authorship provenance for a scientist-contributed hypothesis (Milestone 7)
  author?: string | null;
  created_at: number;
  elo_rating: number; // current tournament rating; see app/elo.py
  win_count: number;
  loss_count: number;
  novelty_score: number | null;
  plausibility_score: number | null;
  testability_score: number | null;
  safety_status: string | null; // outcome of the safety screening gate, if run
  // lifecycle state, e.g. active vs. superseded by a later generation
  status: string | null;
  // proximity/dedup cluster this hypothesis was grouped into
  cluster_id: string | null;
  // true when the idea has no evidence-supported claim: it is still ranked and
  // published under the rank-and-publish policy, but flagged "Unverified". Set
  // by GET /hypotheses.
  unverified?: boolean;
}

/** A literature record cited as supporting or contextual evidence. */
export interface Evidence {
  id: string;
  title: string;
  source: string;
  url: string;
  authors: string[];
  year: number | null;
  /**
   * Full text of the source. Present on owner-facing reads; the public share
   * view omits it because attachment evidence stores the private document
   * body here.
   */
  abstract?: string;
  // whether the full source was reachable when evidence was gathered
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
  tier: string | null; // tournament bracket this match was played in, if tiered
  // Debate depth: 1 = single-turn comparison, >1 = multi-turn scientific
  // debate (top-ranked matchups). Older rows default to 1.
  debate_turns: number;
  created_at: number;
}

/** A weighted relationship in the persisted hypothesis proximity graph. */
export interface ProximityEdge {
  id: number;
  run_id: string;
  source_hypothesis_id: string;
  target_hypothesis_id: string;
  similarity: number;
  degree: string | null;
  cluster_id: string | null;
  method: string | null;
  version: string | null;
  model: string | null;
  updated_at: number | null;
}

/**
 * An exact evidence span an assessor cited for (or against) a claim: the
 * verbatim quote and its character offsets in the source passage, plus the
 * source evidence id and url so a reader can open the exact supporting passage.
 * Older runs may have stored bare passage strings; the display layer tolerates
 * both.
 */
export interface SupportSpan {
  evidence_id: string;
  quote: string;
  start: number;
  end: number;
  source: string;
  source_title?: string;
  url: string;
}

/**
 * One edge of the claim-level entailment graph: an atomic claim of a
 * hypothesis assessed against the retrieved evidence (Milestone 5). The
 * `supporting`/`contradicting` arrays hold provenance-stamped spans; a legacy
 * run may still carry bare passage strings.
 */
export interface ClaimEvidenceRow {
  id: number;
  hypothesis_id: string;
  claim: string;
  // supports | contradicts | insufficient
  label: string;
  // categorical | speculative; legacy rows default to categorical server-side
  claim_role?: string;
  supporting: (SupportSpan | string)[];
  contradicting: (SupportSpan | string)[];
  assessor: string;
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
 * for every provider, built server-side by
 * `report_render.build_report_payload`.
 */
export interface ReportPayload {
  research_goal: string;
  run_mode?: RunMode;
  provider: string;
  /** Ideas released by the safety and contradiction gates. */
  hypothesis_count?: number;
  /** Every idea the run explored, released or not. */
  idea_count?: number;
  /** Released ideas carrying an evidence-supported claim. */
  verified_count?: number;
  evidence_count?: number;
  match_count?: number;
  // counts by classification, e.g. verified/partial/unsupported/unavailable
  citation_summary?: Record<string, number>;
  leaderboard: {id: string; title: string; elo: number}[];
  meta_review?: Record<string, unknown>;
  research_overview?: ResearchOverview;
  knowledge_base?: KnowledgeBaseTopic[];
  agent_insights?: AgentInsights;
  idea_buckets?: {
    high_potential: IdeaBucketEntry[];
    non_viable: IdeaBucketEntry[];
  };
  claim_evidence?: ClaimEvidenceRow[];
  execution_time?: number;
  /**
   * Engine nodes whose output degraded to a placeholder fallback after
   * repeated parse failures (L7). Names the report sections a reader should
   * read as "generation failed" rather than as missing data. Empty/absent on
   * clean runs and on reports written before the field existed.
   */
  degraded_sections?: string[];
}

/** One synthesized technical topic backed by claim-evidence references. */
export interface KnowledgeBaseTopic {
  id: string;
  title: string;
  summary: string;
  detail: string;
  uncertainty?: string;
  reference_ids: string[];
}

/** One meta-review recommendation: where to focus, what to do, and why. */
export interface RecommendedDirection {
  focus_area: string;
  recommendation: string;
  justification: string;
}

/**
 * Run-wide findings and explicit scientific uncertainty.
 *
 * `recommended_directions` admits a bare string because report payloads are
 * persisted: reports written before recommendations kept their three fields
 * hold one flattened string per entry, and those reports still render.
 */
export interface AgentInsights {
  key_findings: string[];
  uncertainties: string[];
  contradictions: string[];
  recommended_directions: (RecommendedDirection | string)[];
  next_experiments: string[];
}

/** An idea's report bucket and the persisted reason for that placement. */
export interface IdeaBucketEntry {
  id: string;
  title: string;
  reason: string;
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
  research_contacts?: {
    candidate_id: string;
    name: string;
    expertise: string;
    justification: string;
    source_id: string;
    source_title: string;
    source_url: string;
    source: string;
  }[];
}

/** A persisted run report with its structured payload and markdown path. */
export interface Report {
  id: string;
  run_id: string;
  payload: ReportPayload;
  markdown_path: string;
  created_at: number;
}

/** One active public Goal Report capability. Tokens return only on creation. */
export interface ReportShare {
  id: string;
  run_id: string;
  token?: string;
  created_at: number;
}

/** Versioned safety decision, including optional human adjudication. */
export interface SafetyDecision {
  id: number;
  stage: string;
  decision: 'allow' | 'redact' | 'hold' | 'block';
  reason: string;
  matches: string[];
  category?: string | null;
  policy_version?: string | null;
  risk_domains: string[];
  requires_review: boolean;
  assessor?: string | null;
  resolution?: 'approved' | 'rejected' | null;
  resolved_by?: string | null;
  resolved_at?: number | null;
}

/**
 * The public-safe subset of a run a share exposes: the fields the shared
 * page renders. The full Run row (configuration, ownership, error state) is
 * never returned through a share token.
 */
export interface SharedRun {
  research_goal: string;
  title?: string | null;
  run_mode?: RunMode;
}

/** Read-only data available through a public share capability. */
export interface SharedGoalReport {
  share_id: string;
  run: SharedRun;
  report: Report;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
}

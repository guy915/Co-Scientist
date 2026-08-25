import type {Report} from './report_types';
/** Lifecycle state of a run as reported by the backend. */
export type RunStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'synthesizing'
  | 'completed'
  | 'failed'
  | 'blocked'
  | 'cancelled'
  // Cooperatively paused, resumable from its last checkpoint. Also the
  // status a run carries while a safety hold sits unresolved -- see
  // `Run.awaiting_decision_count`, which tells the two apart.
  | 'paused';

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
 * Closed-vocabulary discriminator carried as `payload.activity` on every
 * run event (the SSE stream's `StreamEvent.payload` and the `/events`
 * snapshot alike). Mirrors `app.store.event_activity.ACTIVITY_VALUES` on
 * the backend, computed once there from the engine's node/agent table
 * rather than left for each consumer to infer from the event's `type` or
 * free-text stage name. `'other'` is the catch-all: any event kind (or a
 * future engine node) this vocabulary does not name lands there instead
 * of being absent, so a client switching on it always has a case to hit.
 * Optional because events persisted before this field existed, and replayed
 * across a resumed run, carry no `activity` key at all.
 */
export type RunEventActivity =
  | 'planning'
  | 'literature_search'
  | 'drafting'
  | 'review'
  | 'tournament'
  | 'evolution'
  | 'deduplication'
  | 'safety'
  | 'synthesis'
  | 'other';

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
  /** Documents attached to this chat, which the Agent reads each turn. */
  documents: InterviewDocument[];
  created_at: number;
  updated_at: number;
  completed_at: number | null;
}

/** One document attached to a chat, as summarized back to the client. */
export interface InterviewDocument {
  id: string;
  title: string;
  mime_type: string;
  byte_size: number;
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
  /**
   * How many of the run's safety decisions are held `paused` and still
   * unresolved (`requires_review` with no `resolution` yet). Derived on
   * every single-run read rather than persisted -- `status === 'paused'`
   * alone cannot tell a run waiting on a person from a cooperatively
   * paused one, and both read identically without this. Zero (not
   * omitted) for a run that is not paused, or is paused with nothing left
   * to review; served only by the single-run endpoint, not the run list.
   */
  awaiting_decision_count?: number;
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
  // deep verification's verdict: holds | weakened | undermined | unverified,
  // null until it reaches the idea (it only probes the tournament's leaders).
  // "undermined" no longer withholds an idea, so this is the only signal that
  // a published one failed a probe on a fundamental assumption.
  verification_verdict?: string | null;
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

/**
 * One cited source in a Q&A answer's evidence manifest (see
 * `app/qa_manifest.py::build_evidence_manifest`). `n` is the 1-based number
 * the answer's own `[n]` markers refer to.
 */
export interface QaSource {
  n: number;
  evidence_id: string;
  title: string;
  url?: string | null;
  source?: string | null;
  year?: number | null;
  state: string;
  passage?: string | null;
}

/**
 * One persisted message row for a run: scientist steering (`kind:
 * "steering"`) or a grounded Q&A exchange (`kind: "qa"`, question and
 * answer as separate rows). `GET /api/runs/{id}/messages` returns every
 * kind in one chronological list; callers filter by `kind`.
 */
export interface RunMessage {
  id: number;
  run_id: string;
  sender: 'user' | 'system';
  content: string;
  kind: string;
  created_at: number;
  applied: boolean;
  // Present on a Q&A answer row when it cited any sources (see
  // qa.py::_citation_meta); absent otherwise, including on the paired
  // question row.
  meta: {sources?: QaSource[]} | null;
}

/** Read-only data available through a public share capability. */
export interface SharedGoalReport {
  share_id: string;
  run: SharedRun;
  report: Report;
  hypotheses: Hypothesis[];
  evidence: Evidence[];
}

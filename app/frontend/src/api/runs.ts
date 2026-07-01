// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.

import {getClientId} from '@/lib/client_id';
import {
  isOfflineRunId,
  offlineAnswer,
  offlineCancelRun,
  offlineCitations,
  offlineCreateRun,
  offlineEvents,
  offlineEvidence,
  offlineGetRun,
  offlineHypotheses,
  offlineListDemoRuns,
  offlineListMessages,
  offlineListRuns,
  offlineMatches,
  offlineReport,
  offlineReviews,
  offlineSafety,
  offlineSendMessage,
  offlineStartRun,
  offlineStatus,
} from './offline_runs';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';
const OFFLINE_FALLBACK_ENABLED =
  (import.meta.env.VITE_ENABLE_OFFLINE_FALLBACK as string) === 'true';

function clientHeaders(): Record<string, string> {
  return {'X-Client-ID': getClientId()};
}

class ApiUnavailableError extends Error {
  constructor() {
    super('API unavailable');
  }
}

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

/** Research style selected in the AI Co-Scientist setup flow. */
export type RunFocus =
  | 'prefer_evidence'
  | 'balance'
  | 'prefer_novelty'
  | 'breakthrough';

/** Depth preset selected in the AI Co-Scientist setup flow. */
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

/** Structured contents of a run's final synthesis report. */
export interface ReportPayload {
  research_goal: string;
  run_mode?: RunMode;
  profile?: LegacyRunProfile;
  provider: string;
  leaderboard: {id: string; title: string; elo: number}[];
  citation_summary?: Record<string, number>;
  evidence_count?: number;
  matches_count?: number;
  research_overview?: ResearchOverview;
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

/** A chat message exchanged with a run (steering, Q&A, or milestone). */
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

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    if (res.status === 500 && !text.trim()) throw new ApiUnavailableError();
    throw new Error(`${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

function isApiUnavailable(err: unknown): boolean {
  return (
    err instanceof ApiUnavailableError ||
    (err instanceof TypeError &&
      /fetch|network|load failed|failed to fetch/i.test(err.message))
  );
}

function shouldUseOfflineFallback(err: unknown): boolean {
  return OFFLINE_FALLBACK_ENABLED && isApiUnavailable(err);
}

/**
 * Creates a new run from a research goal and optional config overrides.
 *
 * @param input Research goal and optional engine parameters.
 * @returns The newly created run.
 */
export async function createRun(input: {
  research_goal: string;
  run_mode?: RunMode;
  profile?: LegacyRunProfile;
  requirements?: string[];
  attributes?: string[];
  criteria?: string[];
  focus?: RunFocus;
  tier?: RunTier;
  initial_hypotheses_count?: number;
  max_iterations?: number;
  evolution_max_count?: number;
  k_factor?: number;
  enable_literature_review?: boolean;
  notes?: string;
}): Promise<Run> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', ...clientHeaders()},
      body: JSON.stringify(input),
    });
    return await jsonOrThrow<Run>(res);
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineCreateRun(input);
    throw err;
  }
}

/**
 * Lists the runs owned by the current client.
 *
 * @param limit Maximum runs to return.
 * @returns All runs visible to the caller.
 */
export async function listRuns(limit?: number): Promise<Run[]> {
  const query = limit === undefined ? '' : `?limit=${limit}`;
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs${query}`, {
      headers: clientHeaders(),
    });
    const data = await jsonOrThrow<{runs: Run[]}>(res);
    return data.runs;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) {
      const runs = offlineListRuns();
      return limit === undefined ? runs : runs.slice(0, limit);
    }
    throw err;
  }
}

/**
 * Lists the public demonstration runs.
 *
 * @returns The seeded demo runs.
 */
export async function listDemoRuns(): Promise<Run[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/demo`);
    const data = await jsonOrThrow<{runs: Run[]}>(res);
    return data.runs;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineListDemoRuns();
    throw err;
  }
}

/**
 * Fetches a single run together with its artifact summary.
 *
 * @param id Run identifier.
 * @returns The run and its aggregate counts.
 */
export async function getRun(id: string): Promise<RunWithSummary> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}`);
    return await jsonOrThrow<RunWithSummary>(res);
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineGetRun(id);
    throw err;
  }
}

/**
 * Starts generation for a run, optionally forcing a provider.
 *
 * @param id Run identifier.
 * @param body Optional provider override.
 * @returns The run id and its new status.
 */
export async function startRun(
  id: string,
  body: {force_provider?: 'mock' | 'engine'} = {},
): Promise<{id: string; status: string}> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/start`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    return await jsonOrThrow(res);
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineStartRun(id);
    throw err;
  }
}

/**
 * Requests cancellation of an in-progress run.
 *
 * @param id Run identifier.
 * @returns The run id and its new status.
 */
export async function cancelRun(
  id: string,
): Promise<{id: string; status: string}> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/cancel`, {
      method: 'POST',
    });
    return await jsonOrThrow(res);
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineCancelRun(id);
    throw err;
  }
}

/**
 * Fetches the hypotheses generated by a run.
 *
 * @param id Run identifier.
 * @returns The run's hypotheses.
 */
export async function getHypotheses(id: string): Promise<Hypothesis[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/hypotheses`);
    const data = await jsonOrThrow<{hypotheses: Hypothesis[]}>(res);
    return data.hypotheses;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineHypotheses(id);
    throw err;
  }
}

/**
 * Fetches the literature evidence gathered for a run.
 *
 * @param id Run identifier.
 * @returns The run's evidence records.
 */
export async function getEvidence(id: string): Promise<Evidence[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/evidence`);
    const data = await jsonOrThrow<{evidence: Evidence[]}>(res);
    return data.evidence;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineEvidence(id);
    throw err;
  }
}

/**
 * Fetches the pairwise tournament matches for a run.
 *
 * @param id Run identifier.
 * @returns The run's match rows.
 */
export async function getMatches(id: string): Promise<MatchRow[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/matches`);
    const data = await jsonOrThrow<{matches: MatchRow[]}>(res);
    return data.matches;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineMatches(id);
    throw err;
  }
}

/**
 * Fetches the reviewer critiques for a run's hypotheses.
 *
 * @param id Run identifier.
 * @returns The run's reviews.
 */
export async function getReviews(id: string): Promise<Review[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/reviews`);
    const data = await jsonOrThrow<{reviews: Review[]}>(res);
    return data.reviews;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineReviews(id);
    throw err;
  }
}

/**
 * Fetches the safety-gate decisions recorded for a run.
 *
 * @param id Run identifier.
 * @returns The run's safety decisions.
 */
export async function getSafety(id: string): Promise<SafetyDecision[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/safety`);
    const data = await jsonOrThrow<{safety: SafetyDecision[]}>(res);
    return data.safety;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineSafety(id);
    throw err;
  }
}

/**
 * Fetches the claim-to-evidence citations for a run.
 *
 * @param id Run identifier.
 * @returns The run's citation rows.
 */
export async function getCitations(id: string): Promise<CitationRow[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/citations`);
    const data = await jsonOrThrow<{citations: CitationRow[]}>(res);
    return data.citations;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineCitations(id);
    throw err;
  }
}

/**
 * Fetches a run's final report, or null if none exists yet.
 *
 * @param id Run identifier.
 * @returns The report, or null when not yet generated.
 */
export async function getReport(id: string): Promise<Report | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/report`);
    if (res.status === 404) return null;
    return await jsonOrThrow<Report>(res);
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineReport(id);
    throw err;
  }
}

/**
 * Builds the URL for a run's downloadable markdown report.
 *
 * @param id Run identifier.
 * @returns The absolute report.md endpoint URL.
 */
export function reportMarkdownUrl(id: string): string {
  return `${API_BASE_URL}/api/runs/${id}/report.md`;
}

/**
 * Builds the SSE events-stream URL for a run.
 *
 * @param id Run identifier.
 * @param after Sequence number to resume after; 0 replays from the start.
 * @returns The absolute events endpoint URL.
 */
export function eventsStreamUrl(id: string, after = 0): string {
  return `${API_BASE_URL}/api/runs/${id}/events?after=${after}`;
}

/** A single timeline event emitted by the engine during a run. */
export interface RunEvent {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: number;
}

/**
 * Fetches the full persisted event log for a run.
 *
 * @param id Run identifier.
 * @returns The run's events in sequence order.
 */
export async function getRunEventsLog(id: string): Promise<RunEvent[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${id}/events/log`);
    return await jsonOrThrow<RunEvent[]>(res);
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineEvents(id);
    throw err;
  }
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

/**
 * Fetches backend diagnostics for provider and tool availability.
 *
 * @returns The current system status.
 */
export async function getSystemStatus(): Promise<SystemStatus> {
  try {
    const res = await fetch(`${API_BASE_URL}/status`);
    return await jsonOrThrow<SystemStatus>(res);
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineStatus();
    throw err;
  }
}

/**
 * Lists the chat messages for a run.
 *
 * @param runId Run identifier.
 * @returns The run's messages.
 */
export async function listMessages(runId: string): Promise<Message[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${runId}/messages`, {
      headers: clientHeaders(),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      if (res.status === 500 && !text.trim()) throw new ApiUnavailableError();
      throw new Error(`listMessages ${res.status}`);
    }
    const data = (await res.json()) as {messages: Message[]};
    return data.messages;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return offlineListMessages(runId);
    throw err;
  }
}

/**
 * Posts a steering or Q&A message to a run.
 *
 * @param runId Run identifier.
 * @param content Message body.
 * @param kind Message kind; defaults to the server's choice when omitted.
 * @returns The persisted message.
 */
export async function sendMessage(
  runId: string,
  content: string,
  kind?: 'steering' | 'qa',
): Promise<Message> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/runs/${runId}/messages`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', ...clientHeaders()},
      body: JSON.stringify({content, ...(kind ? {kind} : {})}),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      if (res.status === 500 && !text.trim()) throw new ApiUnavailableError();
      throw new Error(`sendMessage ${res.status}`);
    }
    return (await res.json()) as Message;
  } catch (err) {
    if (shouldUseOfflineFallback(err)) {
      return offlineSendMessage(runId, content, kind);
    }
    throw err;
  }
}

/**
 * Builds the streaming endpoint URL for asking a run a question.
 *
 * @param runId Run identifier.
 * @returns The absolute ask endpoint URL.
 */
export function askQuestionUrl(runId: string): string {
  return `${API_BASE_URL}/api/runs/${runId}/messages/ask`;
}

export function canUseOfflineRun(runId: string): boolean {
  return OFFLINE_FALLBACK_ENABLED && isOfflineRunId(runId);
}

export function answerOfflineQuestion(
  runId: string,
  question: string,
): Message {
  return offlineAnswer(runId, question);
}

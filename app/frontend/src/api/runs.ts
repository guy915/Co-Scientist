// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.

import {getClientId} from '@/lib/client_id';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

function clientHeaders(): Record<string, string> {
  return {'X-Client-ID': getClientId()};
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

/** Generation profile that selects the engine's effort/quality preset. */
export type RunProfile = 'standard' | 'advanced';

/** A hypothesis-generation run with its goal, config, and current status. */
export interface Run {
  id: string;
  research_goal: string;
  profile: RunProfile;
  status: RunStatus;
  provider: 'mock' | 'engine';
  config: Record<string, number | string>;
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
  profile: RunProfile;
  provider: string;
  leaderboard: {id: string; title: string; elo: number}[];
  citation_summary?: Record<string, number>;
  evidence_count?: number;
  matches_count?: number;
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
export interface Message {
  id: number;
  run_id: string;
  sender: 'user' | 'system';
  content: string;
  kind: 'steering' | 'qa' | 'milestone';
  created_at: number;
  applied: boolean;
  status?: string;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

/**
 * Creates a new run from a research goal and optional config overrides.
 *
 * @param input Research goal, profile, and optional engine parameters.
 * @returns The newly created run.
 */
export async function createRun(input: {
  research_goal: string;
  profile: RunProfile;
  initial_hypotheses_count?: number;
  max_iterations?: number;
  evolution_max_count?: number;
  k_factor?: number;
  notes?: string;
}): Promise<Run> {
  const res = await fetch(`${API_BASE_URL}/api/runs`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ...clientHeaders()},
    body: JSON.stringify(input),
  });
  return jsonOrThrow<Run>(res);
}

/**
 * Lists the runs owned by the current client.
 *
 * @returns All runs visible to the caller.
 */
export async function listRuns(): Promise<Run[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs`, {
    headers: clientHeaders(),
  });
  const data = await jsonOrThrow<{runs: Run[]}>(res);
  return data.runs;
}

/**
 * Lists the public demonstration runs.
 *
 * @returns The seeded demo runs.
 */
export async function listDemoRuns(): Promise<Run[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/demo`);
  const data = await jsonOrThrow<{runs: Run[]}>(res);
  return data.runs;
}

/**
 * Fetches a single run together with its artifact summary.
 *
 * @param id Run identifier.
 * @returns The run and its aggregate counts.
 */
export async function getRun(id: string): Promise<RunWithSummary> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}`);
  return jsonOrThrow<RunWithSummary>(res);
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
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/start`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  return jsonOrThrow(res);
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
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/cancel`, {
    method: 'POST',
  });
  return jsonOrThrow(res);
}

/**
 * Fetches the hypotheses generated by a run.
 *
 * @param id Run identifier.
 * @returns The run's hypotheses.
 */
export async function getHypotheses(id: string): Promise<Hypothesis[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/hypotheses`);
  const data = await jsonOrThrow<{hypotheses: Hypothesis[]}>(res);
  return data.hypotheses;
}

/**
 * Fetches the literature evidence gathered for a run.
 *
 * @param id Run identifier.
 * @returns The run's evidence records.
 */
export async function getEvidence(id: string): Promise<Evidence[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/evidence`);
  const data = await jsonOrThrow<{evidence: Evidence[]}>(res);
  return data.evidence;
}

/**
 * Fetches the pairwise tournament matches for a run.
 *
 * @param id Run identifier.
 * @returns The run's match rows.
 */
export async function getMatches(id: string): Promise<MatchRow[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/matches`);
  const data = await jsonOrThrow<{matches: MatchRow[]}>(res);
  return data.matches;
}

/**
 * Fetches the reviewer critiques for a run's hypotheses.
 *
 * @param id Run identifier.
 * @returns The run's reviews.
 */
export async function getReviews(id: string): Promise<Review[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/reviews`);
  const data = await jsonOrThrow<{reviews: Review[]}>(res);
  return data.reviews;
}

/**
 * Fetches the safety-gate decisions recorded for a run.
 *
 * @param id Run identifier.
 * @returns The run's safety decisions.
 */
export async function getSafety(id: string): Promise<SafetyDecision[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/safety`);
  const data = await jsonOrThrow<{safety: SafetyDecision[]}>(res);
  return data.safety;
}

/**
 * Fetches the claim-to-evidence citations for a run.
 *
 * @param id Run identifier.
 * @returns The run's citation rows.
 */
export async function getCitations(id: string): Promise<CitationRow[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/citations`);
  const data = await jsonOrThrow<{citations: CitationRow[]}>(res);
  return data.citations;
}

/**
 * Fetches a run's final report, or null if none exists yet.
 *
 * @param id Run identifier.
 * @returns The report, or null when not yet generated.
 */
export async function getReport(id: string): Promise<Report | null> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/report`);
  if (res.status === 404) return null;
  return jsonOrThrow<Report>(res);
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
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/events/log`);
  return jsonOrThrow<RunEvent[]>(res);
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
  const res = await fetch(`${API_BASE_URL}/status`);
  return jsonOrThrow<SystemStatus>(res);
}

/**
 * Lists the chat messages for a run.
 *
 * @param runId Run identifier.
 * @returns The run's messages.
 */
export async function listMessages(runId: string): Promise<Message[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${runId}/messages`, {
    headers: clientHeaders(),
  });
  if (!res.ok) throw new Error(`listMessages ${res.status}`);
  const data = (await res.json()) as {messages: Message[]};
  return data.messages;
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
  const res = await fetch(`${API_BASE_URL}/api/runs/${runId}/messages`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ...clientHeaders()},
    body: JSON.stringify({content, ...(kind ? {kind} : {})}),
  });
  if (!res.ok) throw new Error(`sendMessage ${res.status}`);
  return (await res.json()) as Message;
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

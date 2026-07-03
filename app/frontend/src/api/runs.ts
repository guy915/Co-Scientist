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
import type {
  CitationRow,
  Evidence,
  Hypothesis,
  LegacyRunProfile,
  MatchRow,
  Message,
  Report,
  Review,
  Run,
  RunEvent,
  RunFocus,
  RunMode,
  RunTier,
  RunWithSummary,
  SafetyDecision,
  SystemStatus,
} from './run_types';
export type {
  CitationRow,
  Evidence,
  Hypothesis,
  JsonPrimitive,
  JsonValue,
  LegacyRunProfile,
  MatchRow,
  Message,
  MessageMeta,
  Report,
  ReportPayload,
  ResearchOverview,
  Review,
  Run,
  RunConfig,
  RunEvent,
  RunFocus,
  RunMode,
  RunSetupConfig,
  RunStatus,
  RunSummary,
  RunTier,
  RunWithSummary,
  SafetyDecision,
  SourceRef,
  SystemStatus,
} from './run_types';

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

async function parseJson<T>(res: Response, errorPrefix?: string): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    if (res.status === 500 && !text.trim()) throw new ApiUnavailableError();
    if (errorPrefix) throw new Error(`${errorPrefix} ${res.status}`);
    throw new Error(`${res.status} ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  return parseJson<T>(res, errorPrefix);
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

async function withOfflineFallback<T>(
  request: () => Promise<T>,
  fallback: () => T | Promise<T>,
): Promise<T> {
  try {
    return await request();
  } catch (err) {
    if (shouldUseOfflineFallback(err)) return await fallback();
    throw err;
  }
}

async function fetchWithFallback<T>(
  path: string,
  fallback: () => T | Promise<T>,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T> {
  return withOfflineFallback(
    () => fetchJson<T>(path, init, errorPrefix),
    fallback,
  );
}

async function fetchFieldWithFallback<K extends string, T>(
  path: string,
  field: K,
  fallback: () => T | Promise<T>,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T> {
  const data = await withOfflineFallback(
    () => fetchJson<Record<K, T>>(path, init, errorPrefix),
    async () => ({[field]: await fallback()}) as Record<K, T>,
  );
  return data[field];
}

function jsonRequest(body: unknown, includeClientId = false): RequestInit {
  return {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(includeClientId ? clientHeaders() : {}),
    },
    body: JSON.stringify(body),
  };
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
  return fetchWithFallback(
    '/api/runs',
    () => offlineCreateRun(input),
    jsonRequest(input, true),
  );
}

/**
 * Lists the runs owned by the current client.
 *
 * @param limit Maximum runs to return.
 * @returns All runs visible to the caller.
 */
export async function listRuns(limit?: number): Promise<Run[]> {
  const query = limit === undefined ? '' : `?limit=${limit}`;
  return fetchFieldWithFallback(
    `/api/runs${query}`,
    'runs',
    () => {
      const runs = offlineListRuns();
      return limit === undefined ? runs : runs.slice(0, limit);
    },
    {headers: clientHeaders()},
  );
}

/**
 * Lists the public demonstration runs.
 *
 * @returns The seeded demo runs.
 */
export async function listDemoRuns(): Promise<Run[]> {
  return fetchFieldWithFallback('/api/runs/demo', 'runs', offlineListDemoRuns);
}

/**
 * Fetches a single run together with its artifact summary.
 *
 * @param id Run identifier.
 * @returns The run and its aggregate counts.
 */
export async function getRun(id: string): Promise<RunWithSummary> {
  return fetchWithFallback(`/api/runs/${id}`, () => offlineGetRun(id));
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
  return fetchWithFallback(
    `/api/runs/${id}/start`,
    () => offlineStartRun(id),
    jsonRequest(body),
  );
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
  return fetchWithFallback(
    `/api/runs/${id}/cancel`,
    () => offlineCancelRun(id),
    {method: 'POST'},
  );
}

/**
 * Fetches the hypotheses generated by a run.
 *
 * @param id Run identifier.
 * @returns The run's hypotheses.
 */
export async function getHypotheses(id: string): Promise<Hypothesis[]> {
  return fetchFieldWithFallback(
    `/api/runs/${id}/hypotheses`,
    'hypotheses',
    () => offlineHypotheses(id),
  );
}

/**
 * Fetches the literature evidence gathered for a run.
 *
 * @param id Run identifier.
 * @returns The run's evidence records.
 */
export async function getEvidence(id: string): Promise<Evidence[]> {
  return fetchFieldWithFallback(`/api/runs/${id}/evidence`, 'evidence', () =>
    offlineEvidence(id),
  );
}

/**
 * Fetches the pairwise tournament matches for a run.
 *
 * @param id Run identifier.
 * @returns The run's match rows.
 */
export async function getMatches(id: string): Promise<MatchRow[]> {
  return fetchFieldWithFallback(`/api/runs/${id}/matches`, 'matches', () =>
    offlineMatches(id),
  );
}

/**
 * Fetches the reviewer critiques for a run's hypotheses.
 *
 * @param id Run identifier.
 * @returns The run's reviews.
 */
export async function getReviews(id: string): Promise<Review[]> {
  return fetchFieldWithFallback(`/api/runs/${id}/reviews`, 'reviews', () =>
    offlineReviews(id),
  );
}

/**
 * Fetches the safety-gate decisions recorded for a run.
 *
 * @param id Run identifier.
 * @returns The run's safety decisions.
 */
export async function getSafety(id: string): Promise<SafetyDecision[]> {
  return fetchFieldWithFallback(`/api/runs/${id}/safety`, 'safety', () =>
    offlineSafety(id),
  );
}

/**
 * Fetches the claim-to-evidence citations for a run.
 *
 * @param id Run identifier.
 * @returns The run's citation rows.
 */
export async function getCitations(id: string): Promise<CitationRow[]> {
  return fetchFieldWithFallback(`/api/runs/${id}/citations`, 'citations', () =>
    offlineCitations(id),
  );
}

/**
 * Fetches a run's final report, or null if none exists yet.
 *
 * @param id Run identifier.
 * @returns The report, or null when not yet generated.
 */
export async function getReport(id: string): Promise<Report | null> {
  return withOfflineFallback(
    async () => {
      const res = await fetch(`${API_BASE_URL}/api/runs/${id}/report`);
      if (res.status === 404) return null;
      return parseJson<Report>(res);
    },
    () => offlineReport(id),
  );
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

/**
 * Fetches the full persisted event log for a run.
 *
 * @param id Run identifier.
 * @returns The run's events in sequence order.
 */
export async function getRunEventsLog(id: string): Promise<RunEvent[]> {
  return fetchWithFallback(`/api/runs/${id}/events/log`, () =>
    offlineEvents(id),
  );
}

/**
 * Fetches backend diagnostics for provider and tool availability.
 *
 * @returns The current system status.
 */
export async function getSystemStatus(): Promise<SystemStatus> {
  return fetchWithFallback('/status', offlineStatus);
}

/**
 * Lists the chat messages for a run.
 *
 * @param runId Run identifier.
 * @returns The run's messages.
 */
export async function listMessages(runId: string): Promise<Message[]> {
  return fetchFieldWithFallback(
    `/api/runs/${runId}/messages`,
    'messages',
    () => offlineListMessages(runId),
    {headers: clientHeaders()},
    'listMessages',
  );
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
  return fetchWithFallback(
    `/api/runs/${runId}/messages`,
    () => offlineSendMessage(runId, content, kind),
    jsonRequest({content, ...(kind ? {kind} : {})}, true),
    'sendMessage',
  );
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

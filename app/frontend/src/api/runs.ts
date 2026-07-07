// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.

import {getClientId} from '@/lib/client_id';
import {
  isOfflineRunId,
  offlineCancelRun,
  offlineCreateRun,
  offlineEvents,
  offlineEvidence,
  offlineGetRun,
  offlineHypotheses,
  offlineListDemoRuns,
  offlineListRuns,
  offlineMatches,
  offlineReport,
  offlineReviews,
  offlineStartRun,
} from './offline_runs';
import type {
  Evidence,
  Hypothesis,
  LegacyRunProfile,
  MatchRow,
  Report,
  Review,
  Run,
  RunEvent,
  RunFocus,
  RunMode,
  RunStatus,
  RunTier,
  RunWithSummary,
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

/** Statuses for a run whose workflow is still in progress. */
const ACTIVE_STATUSES: readonly RunStatus[] = [
  'running',
  'queued',
  'synthesizing',
];

/**
 * Whether a run status represents in-progress work.
 *
 * @param status The run status (may be undefined before load).
 * @returns True if the run's workflow is still in progress.
 */
export function isActiveStatus(status: RunStatus | undefined): boolean {
  return Boolean(status && ACTIVE_STATUSES.includes(status));
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
 * Loads the combined run history for the sidebar and home surfaces: owned runs
 * plus demo runs, de-duplicated by id and sorted by `updated_at` descending.
 * Each fetch degrades to an empty list on failure so a single failing source
 * never blocks the other.
 *
 * @returns The merged, sorted run history.
 */
export async function loadRunHistory(): Promise<Run[]> {
  const [ownedRuns, demoRuns] = await Promise.all([
    listRuns().catch(() => [] as Run[]),
    listDemoRuns().catch(() => [] as Run[]),
  ]);
  const byId = new Map<string, Run>();
  for (const item of [...ownedRuns, ...demoRuns]) byId.set(item.id, item);
  return [...byId.values()].sort((a, b) => b.updated_at - a.updated_at);
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
 * Fetches a run sub-resource `/api/runs/{id}/{key}` that the API returns
 * wrapped as `{[key]: T[]}`, with an offline fallback.
 *
 * @param id Run identifier.
 * @param key Sub-resource path segment, doubling as the response key.
 * @param fallback Offline fallback producing the list.
 * @param init Optional fetch options (e.g. client headers).
 * @param errorPrefix Optional prefix for error messages.
 * @returns The unwrapped array.
 */
async function getRunList<T>(
  id: string,
  key: string,
  fallback: () => T[] | Promise<T[]>,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T[]> {
  return fetchFieldWithFallback(
    `/api/runs/${id}/${key}`,
    key,
    fallback,
    init,
    errorPrefix,
  );
}

/**
 * Fetches the hypotheses generated by a run.
 *
 * @param id Run identifier.
 * @returns The run's hypotheses.
 */
export function getHypotheses(id: string): Promise<Hypothesis[]> {
  return getRunList<Hypothesis>(id, 'hypotheses', () => offlineHypotheses(id));
}

/**
 * Fetches the literature evidence gathered for a run.
 *
 * @param id Run identifier.
 * @returns The run's evidence records.
 */
export function getEvidence(id: string): Promise<Evidence[]> {
  return getRunList<Evidence>(id, 'evidence', () => offlineEvidence(id));
}

/**
 * Fetches the pairwise tournament matches for a run.
 *
 * @param id Run identifier.
 * @returns The run's match rows.
 */
export function getMatches(id: string): Promise<MatchRow[]> {
  return getRunList<MatchRow>(id, 'matches', () => offlineMatches(id));
}

/**
 * Fetches the reviewer critiques for a run's hypotheses.
 *
 * @param id Run identifier.
 * @returns The run's reviews.
 */
export function getReviews(id: string): Promise<Review[]> {
  return getRunList<Review>(id, 'reviews', () => offlineReviews(id));
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
 * Builds the SSE events-stream URL for a run. The stream always replays from
 * the start; the backend treats a missing cursor as `after=0`.
 *
 * @param id Run identifier.
 * @returns The absolute events endpoint URL.
 */
export function eventsStreamUrl(id: string): string {
  return `${API_BASE_URL}/api/runs/${id}/events`;
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

export function canUseOfflineRun(runId: string): boolean {
  return OFFLINE_FALLBACK_ENABLED && isOfflineRunId(runId);
}

// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.

import {getClientId} from '@/lib/client_id';
import {mergeByIdNewestFirst} from '@/lib/merge';
import type {
  Evidence,
  Hypothesis,
  MatchRow,
  Report,
  Review,
  Run,
  RunFocus,
  RunStatus,
  RunTier,
  RunWithSummary,
} from './run_types';
// Re-export the run-domain types so callers can `import type {...} from
// '@/api/runs'` alongside the API functions below, without a second import
// from './run_types'.
export type {
  Evidence,
  Hypothesis,
  JsonPrimitive,
  JsonValue,
  LegacyRunProfile,
  MatchRow,
  Report,
  ReportPayload,
  ResearchOverview,
  Review,
  Run,
  RunConfig,
  RunFocus,
  RunMode,
  RunSetupConfig,
  RunStatus,
  RunSummary,
  RunTier,
  RunWithSummary,
} from './run_types';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

/** Header identifying the calling browser client to the backend. */
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

/**
 * Returns the first value in `values` that is neither null nor undefined, or
 * undefined when every value is nullish.
 */
function firstDefined<T>(
  ...values: Array<T | null | undefined>
): T | undefined {
  return values.find(
    (value): value is T => value !== null && value !== undefined,
  );
}

/**
 * The run's effective goal: the durable setup goal when set, else the
 * top-level research goal. Returns '' when the run is not yet loaded.
 */
export function runGoal(run: Run | null | undefined): string {
  return firstDefined(run?.config.setup?.goal, run?.research_goal) ?? '';
}

/**
 * Builds the error message for a non-ok response: a clearer message for an
 * empty-bodied 500 (the API process itself is typically unreachable, e.g.
 * cold start or a proxy with no upstream, rather than a handled application
 * error), else the caller's prefix, else the raw status and body.
 */
function responseErrorMessage(
  status: number,
  statusText: string,
  text: string,
  errorPrefix?: string,
): string {
  if (status === 500 && !text.trim()) return 'API unavailable';
  if (errorPrefix) return `${errorPrefix} ${status}`;
  return `${status} ${text || statusText}`;
}

/**
 * Parses a fetch `Response` as JSON, or throws a descriptive `Error` when the
 * response was not ok.
 */
async function parseJson<T>(res: Response, errorPrefix?: string): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(
      responseErrorMessage(res.status, res.statusText, text, errorPrefix),
    );
  }
  return (await res.json()) as T;
}

/** Fetches `path` relative to the API base URL and parses the JSON body. */
async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  return parseJson<T>(res, errorPrefix);
}

/**
 * Fetches a `{[field]: T}` envelope and unwraps the named field.
 *
 * @param path Request path.
 * @param field Response key to unwrap.
 * @param init Optional fetch options (e.g. client headers).
 * @param errorPrefix Optional prefix for error messages.
 * @returns The unwrapped value.
 */
async function fetchField<K extends string, T>(
  path: string,
  field: K,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T> {
  const data = await fetchJson<Record<K, T>>(path, init, errorPrefix);
  return data[field];
}

/**
 * Builds a JSON POST `RequestInit`. `includeClientId` is opt-in because only
 * endpoints that scope data by owning client (e.g. creating/listing runs)
 * need the `X-Client-ID` header.
 */
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
}): Promise<Run> {
  return fetchJson('/api/runs', jsonRequest(input, true));
}

/**
 * Lists the runs owned by the current client.
 *
 * @param limit Maximum runs to return.
 * @returns All runs visible to the caller.
 */
export async function listRuns(limit?: number): Promise<Run[]> {
  const query = limit === undefined ? '' : `?limit=${limit}`;
  return fetchField(`/api/runs${query}`, 'runs', {headers: clientHeaders()});
}

/**
 * Lists the public demonstration runs.
 *
 * @returns The seeded demo runs.
 */
export async function listDemoRuns(): Promise<Run[]> {
  return fetchField('/api/runs/demo', 'runs');
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
  return mergeByIdNewestFirst(
    [...ownedRuns, ...demoRuns],
    run => run.id,
    run => run.updated_at,
  );
}

/**
 * Fetches a single run together with its artifact summary.
 *
 * @param id Run identifier.
 * @returns The run and its aggregate counts.
 */
export async function getRun(id: string): Promise<RunWithSummary> {
  return fetchJson(`/api/runs/${id}`);
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
  return fetchJson(`/api/runs/${id}/start`, jsonRequest(body));
}

/**
 * Fetches a run sub-resource `/api/runs/{id}/{key}` that the API returns
 * wrapped as `{[key]: T[]}`.
 *
 * @param id Run identifier.
 * @param key Sub-resource path segment, doubling as the response key.
 * @param init Optional fetch options (e.g. client headers).
 * @param errorPrefix Optional prefix for error messages.
 * @returns The unwrapped array.
 */
function getRunList<T>(
  id: string,
  key: string,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T[]> {
  return fetchField<string, T[]>(
    `/api/runs/${id}/${key}`,
    key,
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
  return getRunList<Hypothesis>(id, 'hypotheses');
}

/**
 * Fetches the literature evidence gathered for a run.
 *
 * @param id Run identifier.
 * @returns The run's evidence records.
 */
export function getEvidence(id: string): Promise<Evidence[]> {
  return getRunList<Evidence>(id, 'evidence');
}

/**
 * Fetches the pairwise tournament matches for a run.
 *
 * @param id Run identifier.
 * @returns The run's match rows.
 */
export function getMatches(id: string): Promise<MatchRow[]> {
  return getRunList<MatchRow>(id, 'matches');
}

/**
 * Fetches the reviewer critiques for a run's hypotheses.
 *
 * @param id Run identifier.
 * @returns The run's reviews.
 */
export function getReviews(id: string): Promise<Review[]> {
  return getRunList<Review>(id, 'reviews');
}

/**
 * Fetches a run's final report, or null if none exists yet.
 *
 * @param id Run identifier.
 * @returns The report, or null when not yet generated.
 */
export async function getReport(id: string): Promise<Report | null> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/report`);
  if (res.status === 404) return null; // no report yet, not an error
  return parseJson<Report>(res);
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

// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.

import {getAccessToken, getClientId} from '@/lib/client_id';
import {mergeByIdNewestFirst} from '@/lib/merge';
import type {
  ClaimEvidenceRow,
  Evidence,
  Hypothesis,
  Interview,
  MatchRow,
  ProximityEdge,
  Report,
  ReportShare,
  Review,
  Run,
  RunFocus,
  RunStatus,
  RunTier,
  RunWithSummary,
  SafetyDecision,
  SharedGoalReport,
} from './run_types';
// Re-export the run-domain types so callers can `import type {...} from
// '@/api/runs'` alongside the API functions below, without a second import
// from './run_types'.
export type {
  AgentInsights,
  ClaimEvidenceRow,
  Evidence,
  Hypothesis,
  Interview,
  InterviewFields,
  InterviewTurn,
  IdeaBucketEntry,
  JsonPrimitive,
  JsonValue,
  KnowledgeBaseTopic,
  LegacyRunProfile,
  MatchRow,
  ProximityEdge,
  Report,
  ReportPayload,
  ReportShare,
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
  SafetyDecision,
  SharedGoalReport,
  SupportSpan,
} from './run_types';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

/** Exchange a configured researcher invite code for a signed session. */
export function exchangeAccessCode(
  accessCode: string,
): Promise<{access_token: string; researcher_id: string; expires_in: number}> {
  return fetchJson('/api/auth/exchange', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({access_code: accessCode}),
  });
}

/** Header identifying the calling browser client to the backend. */
function clientHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token
    ? {Authorization: `Bearer ${token}`}
    : {'X-Client-ID': getClientId()};
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
function firstDefined<T>(...values: (T | null | undefined)[]): T | undefined {
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

/**
 * Fetches `path` relative to the API base URL and parses the JSON body.
 * Exported for sibling API clients (e.g. `@/api/system`) so the base-URL
 * and error-shaping policy stays defined once.
 */
export async function fetchJson<T>(
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
  interview_id?: string;
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
  notify_on_completion?: boolean;
  completion_email?: string;
}): Promise<Run> {
  return fetchJson('/api/runs', jsonRequest(input, true));
}

/** Starts a durable model-driven research-goal interview. */
export async function createInterview(
  researchChallenge: string,
): Promise<Interview> {
  return fetchJson(
    '/api/interviews',
    jsonRequest({research_challenge: researchChallenge}, true),
  );
}

/** Sends one scientist answer and returns the Agent's updated derivation. */
export async function addInterviewTurn(
  interviewId: string,
  content: string,
): Promise<Interview> {
  return fetchJson(
    `/api/interviews/${interviewId}/turns`,
    jsonRequest({content}, true),
  );
}

/** Reloads a durable interview for resume. */
export async function getInterview(interviewId: string): Promise<Interview> {
  return fetchJson(`/api/interviews/${interviewId}`, {
    headers: clientHeaders(),
  });
}

/** Persists scientist edits to the four verified fields. */
export async function editInterviewFields(
  interviewId: string,
  fields: Interview['fields'],
): Promise<Interview> {
  return fetchJson(
    `/api/interviews/${interviewId}/fields`,
    jsonRequest(fields, true),
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
  return fetchJson(`/api/runs/${id}`, {headers: clientHeaders()});
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
  return fetchJson(`/api/runs/${id}/start`, jsonRequest(body, true));
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
    init || {headers: clientHeaders()},
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

/** Fetch the versioned safety audit trail for a run. */
export function getSafety(id: string): Promise<SafetyDecision[]> {
  return getRunList<SafetyDecision>(id, 'safety');
}

/** Resolve one held safety decision as the identified run owner. */
export function adjudicateSafety(
  runId: string,
  decisionId: number,
  resolution: 'approved' | 'rejected',
): Promise<{decision_id: number; resolution: string}> {
  return fetchJson(`/api/runs/${runId}/safety/${decisionId}/adjudicate`, {
    method: 'POST',
    headers: {...clientHeaders(), 'Content-Type': 'application/json'},
    body: JSON.stringify({resolution}),
  });
}

/**
 * Fetches the claim-level entailment graph for a run's hypotheses.
 *
 * The endpoint path (`claim-evidence`) differs from the response key
 * (`claim_evidence`), so this cannot use the `getRunList` shorthand.
 *
 * @param id Run identifier.
 * @returns The run's claim-evidence edges.
 */
export function getClaimEvidence(id: string): Promise<ClaimEvidenceRow[]> {
  return fetchField<'claim_evidence', ClaimEvidenceRow[]>(
    `/api/runs/${id}/claim-evidence`,
    'claim_evidence',
    {headers: clientHeaders()},
  );
}

/** Return the persisted weighted hypothesis proximity graph. */
export function getProximity(id: string): Promise<ProximityEdge[]> {
  return fetchJson<{proximity: ProximityEdge[]}>(
    `/api/runs/${id}/proximity`,
  ).then(response => response.proximity);
}

/** Submit a scientist-authored hypothesis through the shared safety gate. */
export function addScientistHypothesis(
  runId: string,
  input: {title?: string; statement: string; author: string},
): Promise<{admitted: boolean; id?: string; safety: {outcome: string}}> {
  return fetchJson(`/api/runs/${runId}/hypotheses`, jsonRequest(input, true));
}

/** Attach a scientist verdict to an existing hypothesis. */
export function addScientistReview(
  runId: string,
  input: {
    hypothesis_id: string;
    author: string;
    verdict: 'support' | 'oppose' | 'revise';
    critique: string;
  },
): Promise<{recorded: boolean}> {
  return fetchJson(`/api/runs/${runId}/reviews`, jsonRequest(input, true));
}

/** Upload and index a private scientific document for subsequent tasks. */
export function uploadRunDocument(
  runId: string,
  file: File,
): Promise<{
  id: string;
  indexed: boolean;
  sha256: string;
  byte_size: number;
  mime_type: string;
  extraction_tool: string;
}> {
  const body = new FormData();
  body.set('file', file);
  body.set('consent', 'true');
  return fetchJson(`/api/runs/${runId}/attachments/upload`, {
    method: 'POST',
    headers: clientHeaders(),
    body,
  });
}

/**
 * Fetches a run's final report, or null if none exists yet.
 *
 * @param id Run identifier.
 * @returns The report, or null when not yet generated.
 */
export async function getReport(id: string): Promise<Report | null> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${id}/report`, {
    headers: clientHeaders(),
  });
  if (res.status === 404) return null; // no report yet, not an error
  return parseJson<Report>(res);
}

/** Returns the browser-download URL for a persisted Markdown Goal Report. */
export function reportMarkdownUrl(id: string): string {
  const token = getAccessToken();
  const query = token
    ? `access_token=${encodeURIComponent(token)}`
    : `client_id=${encodeURIComponent(getClientId())}`;
  return `${API_BASE_URL}/api/runs/${id}/report.md?${query}`;
}

/** Streams a grounded report-level or idea-level Agent answer to completion. */
export async function askRunQuestion(
  id: string,
  question: string,
): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/api/runs/${id}/messages/ask`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ...clientHeaders()},
    body: JSON.stringify({question}),
  });
  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let answer = '';
  while (true) {
    const {done, value} = await reader.read();
    pending += decoder.decode(value, {stream: !done});
    const frames = pending.split('\n\n');
    pending = frames.pop() || '';
    for (const frame of frames) {
      const data = frame
        .split('\n')
        .find(line => line.startsWith('data: '))
        ?.slice(6);
      if (!data) continue;
      const event = JSON.parse(data) as {type: string; content?: string};
      if (event.type === 'chunk') answer += event.content || '';
    }
    if (done) break;
  }
  return answer;
}

/** Enables public read-only access and returns the one-time bearer token. */
export function createReportShare(id: string): Promise<ReportShare> {
  return fetchJson(`/api/runs/${id}/shares`, jsonRequest({}, true));
}

/** Lists active grants without disclosing their bearer tokens. */
export function listReportShares(id: string): Promise<ReportShare[]> {
  return fetchField(`/api/runs/${id}/shares`, 'shares', {
    headers: clientHeaders(),
  });
}

/** Revokes one public report capability. */
export async function revokeReportShare(
  runId: string,
  shareId: string,
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/runs/${runId}/shares/${shareId}`,
    {method: 'DELETE', headers: clientHeaders()},
  );
  if (!response.ok) throw new Error(await response.text());
}

/** Loads a public read-only Goal Report without a client ownership header. */
export function getSharedGoalReport(token: string): Promise<SharedGoalReport> {
  return fetchJson(`/api/shared/${token}`);
}

/**
 * Builds the SSE events-stream URL for a run. The stream always replays from
 * the start; the backend treats a missing cursor as `after=0`.
 *
 * @param id Run identifier.
 * @returns The absolute events endpoint URL.
 */
export function eventsStreamUrl(id: string): string {
  const token = getAccessToken();
  const query = token
    ? `access_token=${encodeURIComponent(token)}`
    : `client_id=${encodeURIComponent(getClientId())}`;
  return `${API_BASE_URL}/api/runs/${id}/events?${query}`;
}

/** One persisted row of a run's append-only event log. */
export interface RunEvent {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: number;
}

/**
 * Fetches a run's persisted event log as a one-shot JSON snapshot
 * (`stream=false`), rather than the SSE stream the run views tail.
 *
 * @param id Run identifier.
 * @param after Only return events with a sequence number greater than this.
 * @returns The persisted events, ordered by sequence number.
 */
export function getRunEvents(id: string, after = 0): Promise<RunEvent[]> {
  return fetchField(
    `/api/runs/${id}/events?stream=false&after=${after}`,
    'events',
    {headers: clientHeaders()},
  );
}

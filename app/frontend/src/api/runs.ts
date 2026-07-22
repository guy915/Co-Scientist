// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.
//
// The client is split across sibling modules, all re-exported here so
// callers keep importing everything from '@/api/runs':
// - runs_http.ts: shared fetch/auth primitives
// - runs_interviews.ts: the research-goal interview
// - runs_collections.ts: per-run collections, reports, and shares

import {mergeByIdNewestFirst} from '@/lib/merge';
import type {
  Audience,
  Run,
  RunFocus,
  RunStatus,
  RunTier,
  RunWithSummary,
} from './run_types';
import {
  API_BASE_URL,
  authQuery,
  clientHeaders,
  fetchField,
  fetchJson,
  jsonRequest,
  readSseFrames,
} from './runs_http';
// Re-export the run-domain types so callers can `import type {...} from
// '@/api/runs'` alongside the API functions below, without a second import
// from './run_types'.
export type {
  AgentInsights,
  Audience,
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
export {clientHeaders, exchangeAccessCode, fetchJson} from './runs_http';
export {
  addInterviewTurn,
  createInterview,
  editInterviewFields,
  getInterview,
} from './runs_interviews';
export {
  addScientistHypothesis,
  addScientistReview,
  adjudicateSafety,
  createReportShare,
  getClaimEvidence,
  getEvidence,
  getHypotheses,
  getMatches,
  getProximity,
  getReport,
  getReviews,
  getSafety,
  getSharedGoalReport,
  listReportShares,
  reportMarkdownUrl,
  revokeReportShare,
  uploadRunDocument,
} from './runs_collections';

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
 * The run's effective goal: the durable setup goal when set, else the
 * top-level research goal. Returns '' when the run is not yet loaded.
 */
export function runGoal(run: Run | null | undefined): string {
  return run?.config.setup?.goal ?? run?.research_goal ?? '';
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
  enable_web_search?: boolean;
  enable_paper_corpus?: boolean;
  notify_on_completion?: boolean;
  completion_email?: string;
  audience?: Audience;
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
export async function loadRunHistory(includeDemos = true): Promise<Run[]> {
  const [ownedRuns, demoRuns] = await Promise.all([
    listRuns().catch(() => [] as Run[]),
    includeDemos ? listDemoRuns().catch(() => [] as Run[]) : [],
  ]);
  // When demos are excluded, deterministic fixtures are never presented as
  // prior scientific work, including legacy mock rows owned by this client.
  const visibleOwnedRuns = includeDemos
    ? ownedRuns
    : ownedRuns.filter(run => run.provider === 'engine');
  return mergeByIdNewestFirst(
    [...visibleOwnedRuns, ...demoRuns],
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

/** Streams a grounded report-level or idea-level Agent answer to completion. */
export async function askRunQuestion(
  id: string,
  question: string,
  audience?: Audience,
): Promise<string> {
  const res = await fetch(
    `${API_BASE_URL}/api/runs/${id}/messages/ask`,
    jsonRequest({question, audience}, true),
  );
  let answer = '';
  interface AnswerFrame {
    type: string;
    content?: string;
  }
  for await (const frame of readSseFrames<AnswerFrame>(res)) {
    if (frame.type === 'chunk') answer += frame.content || '';
  }
  return answer;
}

/** Queue scientist guidance for incorporation at the next safe task boundary. */
export function sendRunSteering(
  id: string,
  content: string,
): Promise<{id: string; status: string}> {
  return fetchJson(`/api/runs/${id}/messages`, jsonRequest({content}, true));
}

/**
 * Builds the SSE events-stream URL for a run. The stream always replays from
 * the start; the backend treats a missing cursor as `after=0`.
 *
 * @param id Run identifier.
 * @returns The absolute events endpoint URL.
 */
export function eventsStreamUrl(id: string): string {
  return `${API_BASE_URL}/api/runs/${id}/events?${authQuery()}`;
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

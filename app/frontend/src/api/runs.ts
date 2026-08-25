// Run lifecycle API client. Mirrors the FastAPI router in app/runs.py.
//
// The client is split across sibling modules, all re-exported here so
// callers keep importing everything from '@/api/runs':
// - runs_http.ts: shared fetch/auth primitives
// - runs_interviews.ts: the research-goal interview
// - runs_qa.ts: grounded Q&A over a started run
// - runs_collections.ts: per-run collections, reports, and shares

import {mergeByIdNewestFirst} from '@/lib/merge';
import type {DiscoverySpec} from './discovery_types';
import type {
  Audience,
  Run,
  RunFocus,
  RunStatus,
  RunTier,
  RunWithSummary,
} from './run_types';
export type {
  AgentInsights,
  IdeaBucketEntry,
  KnowledgeBaseTopic,
  RecommendedDirection,
  Report,
  ReportPayload,
  ResearchOverview,
} from './report_types';
export type {
  CodeVariant,
  CodeVariantPage,
  DiscoveryConfig,
  DiscoveryObjective,
  DiscoveryReportPayload,
  DiscoverySpec,
  VariantStage,
} from './discovery_types';
export {discoveryReportPayload, primaryObjective} from './discovery_types';
import {
  API_BASE_URL,
  byokHeaders,
  clientHeaders,
  fetchField,
  fetchJson,
  jsonRequest,
} from './runs_http';
// Re-export the run-domain types so callers can `import type {...} from
// '@/api/runs'` alongside the API functions below, without a second import
// from './run_types'.
export type {
  Audience,
  ChatSummary,
  ClaimEvidenceRow,
  Evidence,
  Hypothesis,
  Interview,
  InterviewDocument,
  InterviewFields,
  InterviewTurn,
  JsonPrimitive,
  JsonValue,
  LegacyRunProfile,
  MatchRow,
  ProximityEdge,
  QaSource,
  ReportShare,
  Review,
  Run,
  RunConfig,
  RunFocus,
  RunMessage,
  RunMode,
  RunSetupConfig,
  RunStatus,
  RunSummary,
  RunTier,
  RunWithSummary,
  SafetyDecision,
  SharedGoalReport,
  SharedRun,
  SupportSpan,
} from './run_types';
export {
  byokHeaders,
  clientHeaders,
  exchangeAccessCode,
  fetchJson,
  HttpError,
  jsonRequest,
  readSseFrames,
} from './runs_http';
export type {StagedDocument} from './documents';
export {stageDocument} from './documents';
export {
  addInterviewTurn,
  createInterview,
  editInterviewFields,
  editInterviewTurn,
  getInterview,
  listInterviews,
  retryInterviewTurn,
} from './runs_interviews';
export type {InterviewSinks} from './runs_interviews';
export {askRunQuestion, getRunMessages} from './runs_qa';
export type {QaSinks} from './runs_qa';
export {
  addScientistHypothesis,
  addScientistReview,
  adjudicateSafety,
  createReportShare,
  fetchReportMarkdown,
  getClaimEvidence,
  getCodeVariant,
  getCodeVariants,
  getEvidence,
  getHypotheses,
  getMatches,
  getProximity,
  getReport,
  getReviews,
  getSafety,
  getSharedGoalReport,
  listReportShares,
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

/** Statuses for a run that has settled and will run no further tasks. */
const TERMINAL_STATUSES: readonly RunStatus[] = [
  'completed',
  'failed',
  'blocked',
  'cancelled',
];

/**
 * Whether a run has reached a terminal state.
 *
 * Distinct from `!isActiveStatus`: a `draft` run is neither active nor
 * terminal — it has not started, so new documents it is given will still be
 * indexed once it runs.
 *
 * @param status The run status (may be undefined before load).
 * @returns True if the run has settled and will run no further tasks.
 */
export function isTerminalStatus(status: RunStatus | undefined): boolean {
  return Boolean(status && TERMINAL_STATUSES.includes(status));
}

/**
 * The run's effective goal: the durable setup goal when set, else the
 * top-level research goal. Returns '' when the run is not yet loaded.
 */
export function runGoal(run: Run | null | undefined): string {
  if (!run) return '';
  return run.config.setup?.goal ?? run.research_goal ?? '';
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
  // Documents staged through POST /api/documents before this call. Creation
  // copies them into the run's corpus, so the run is grounded the moment it
  // exists rather than by a follow-up upload that can fail on its own.
  document_ids?: string[];
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
  // Makes this a computational-discovery run: it evolves a program
  // against a measured objective instead of generating hypotheses. The
  // shape is owned by the backend's `discovery_spec`, which validates it
  // on this call -- a malformed one is a 422, not a run that fails
  // identically on every variant.
  discovery?: DiscoverySpec;
}): Promise<Run> {
  const init = jsonRequest(input, true);
  // Bring-your-own-key: the stored key/provider ride along as request
  // headers; the backend validates the pair before accepting the run.
  return fetchJson('/api/runs', {
    ...init,
    headers: {
      ...(init.headers as Record<string, string>),
      ...byokHeaders(),
    },
  });
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

/**
 * Settles a run that is not going to proceed.
 *
 * Used as the compensating half of run setup: when starting a just-created
 * run fails, the run is settled here rather than left as a draft that
 * nothing points at and nothing will ever pick up.
 *
 * @param id Run identifier.
 * @returns The run id and its new status.
 */
export async function cancelRun(
  id: string,
): Promise<{id: string; status: string}> {
  return fetchJson(`/api/runs/${id}/cancel`, jsonRequest({}, true));
}

/**
 * Permanently deletes a terminal run and every row scoped to it. Cannot be
 * undone; the run must not be active (cancel it first).
 *
 * @param id Run identifier.
 * @returns The deleted run's id and the per-table row counts removed.
 */
export async function deleteRun(
  id: string,
): Promise<{id: string; deleted: boolean; counts: Record<string, number>}> {
  return fetchJson(`/api/runs/${id}`, {
    method: 'DELETE',
    headers: clientHeaders(),
  });
}

/** Queue scientist guidance for the next safe task boundary. */
export function sendRunSteering(
  id: string,
  content: string,
): Promise<{id: string; status: string}> {
  return fetchJson(`/api/runs/${id}/messages`, jsonRequest({content}, true));
}

/**
 * Builds the events-stream URL for a run. The stream always replays from the
 * start; the backend treats a missing cursor as `after=0`.
 *
 * Carries no credential: unlike a browser-native `EventSource` (which cannot
 * attach a header), the stream is opened over `fetch` with `clientHeaders()`
 * (see `useRunStream`), so identity travels as a header rather than a query
 * parameter that would otherwise leak into browser history, proxy logs, and
 * referrers.
 *
 * @param id Run identifier.
 * @returns The absolute events endpoint URL.
 */
export function eventsStreamUrl(id: string): string {
  return `${API_BASE_URL}/api/runs/${id}/events`;
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

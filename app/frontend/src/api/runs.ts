import type {Run, RunWithSummary} from './wire_runs';
import type {RunFocus, RunTier, RunStatus} from './wire_common';
import {
  byokHeaders,
  clientHeaders,
  fetchField,
  fetchJson,
  jsonRequest,
} from './runs_http';
export type * from './wire_common';
export type * from './wire_runs';
export type * from './wire_science';
export type * from './wire_interviews';
export type * from './wire_reports';
export {
  byokHeaders,
  clientHeaders,
  exchangeAccessCode,
  fetchJson,
  HttpError,
  jsonRequest,
  readSseFrames,
} from './runs_http';
export * from './runs_interviews';
export * from './runs_qa';
export * from './runs_collections';

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
export function createRun(
  input: {
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
    notify_on_completion?: boolean;
    completion_email?: string;
  },
  options?: {idempotencyKey?: string},
): Promise<Run> {
  const init = jsonRequest(input, true);
  // Bring-your-own-key: the stored key/provider ride along as request
  // headers; the backend validates the pair before accepting the run.
  return fetchJson('/api/runs', {
    ...init,
    headers: {
      ...init.headers,
      ...byokHeaders(),
      ...(options?.idempotencyKey
        ? {'Idempotency-Key': options.idempotencyKey}
        : {}),
    },
  });
}

/**
 * Lists the runs owned by the current client.
 *
 * @param limit Maximum runs to return.
 * @returns All runs visible to the caller.
 */
export function listRuns(limit?: number): Promise<Run[]> {
  const query = limit === undefined ? '' : `?limit=${limit}`;
  return fetchField(`/api/runs${query}`, 'runs', {headers: clientHeaders()});
}

/**
 * Lists the public demonstration runs.
 *
 * @returns The seeded demo runs.
 */
export function listDemoRuns(): Promise<Run[]> {
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
  const byId = new Map([...ownedRuns, ...demoRuns].map(run => [run.id, run]));
  return [...byId.values()].sort((a, b) => b.updated_at - a.updated_at);
}

/**
 * Fetches a single run together with its artifact summary.
 *
 * @param id Run identifier.
 * @returns The run and its aggregate counts.
 */
export function getRun(id: string): Promise<RunWithSummary> {
  return fetchJson(`/api/runs/${id}`, {headers: clientHeaders()});
}

/** Start the durable engine workflow for a run. */
export function startRun(id: string): Promise<{id: string; status: string}> {
  return fetchJson(`/api/runs/${id}/start`, jsonRequest({}, true));
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
export function cancelRun(id: string): Promise<{id: string; status: string}> {
  return fetchJson(`/api/runs/${id}/cancel`, jsonRequest({}, true));
}

/** A document staged against the caller before a run exists. */
export interface StagedDocument {
  id: string;
  title: string;
  sha256: string;
  byte_size: number;
  mime_type: string;
  extraction_tool: string;
}

/** Extract a composer attachment; its id travels with the interview/run. */
export function stageDocument(file: File): Promise<StagedDocument> {
  const body = new FormData();
  body.set('file', file);
  body.set('consent', 'true');
  return fetchJson('/api/documents', {
    method: 'POST',
    headers: clientHeaders(),
    body,
  });
}

type StatusInput = string | null | undefined;
type ActiveStatus = Extract<RunStatus, 'queued' | 'running' | 'synthesizing'>;
type FailureStatus = Extract<RunStatus, 'failed' | 'blocked'>;
export type TerminalNonCompletedStatus = FailureStatus | 'cancelled';

/** Paused runs have started, but their workflow is not progressing. */
export function isActiveStatus(status: StatusInput): status is ActiveStatus {
  return (
    status === 'queued' || status === 'running' || status === 'synthesizing'
  );
}

export function isFailureStatus(status: StatusInput): status is FailureStatus {
  return status === 'failed' || status === 'blocked';
}

export function isDraftStatus(status: StatusInput): status is 'draft' {
  return status === 'draft';
}

export function isCompletedStatus(status: StatusInput): status is 'completed' {
  return status === 'completed';
}

export function isCancelledStatus(status: StatusInput): status is 'cancelled' {
  return status === 'cancelled';
}

/** Terminal runs without a report keep a distinct end-state view. */
export function isTerminalNonCompletedStatus(
  status: StatusInput,
): status is TerminalNonCompletedStatus {
  return isFailureStatus(status) || isCancelledStatus(status);
}

/** Draft and paused runs are neither active nor terminal. */
export function isTerminalStatus(
  status: StatusInput,
): status is TerminalNonCompletedStatus | 'completed' {
  return isTerminalNonCompletedStatus(status) || isCompletedStatus(status);
}

export function isStoppableStatus(
  status: StatusInput,
): status is ActiveStatus | 'paused' {
  return isActiveStatus(status) || status === 'paused';
}

/** Failed/blocked starts remain errors even though the run is terminal. */
export function isStartedStatus(
  status: StatusInput,
): status is ActiveStatus | 'paused' | 'completed' {
  return isStoppableStatus(status) || isCompletedStatus(status);
}

/** Failed/blocked runs retain their receipt so Start retries don't duplicate. */
export function retiresStartIntent(
  status: StatusInput,
): status is ActiveStatus | 'paused' | 'completed' | 'cancelled' {
  return isStartedStatus(status) || isCancelledStatus(status);
}

export type RunActivity = 'active' | 'inactive' | 'unknown';

/** Wait for a status before choosing between the live view and results. */
export function runActivity(status: StatusInput): RunActivity {
  if (!status) return 'unknown';
  return isActiveStatus(status) ? 'active' : 'inactive';
}

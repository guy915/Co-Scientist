import {mergeByIdNewestFirst} from '@/lib/merge';
import type {Run, RunFocus, RunTier, RunWithSummary} from './run_types';
import {
  byokHeaders,
  clientHeaders,
  fetchField,
  fetchJson,
  jsonRequest,
} from './runs_http';
export type * from './run_types';
export type * from './report_types';
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
export * from './run_lifecycle';

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
export function getRun(id: string): Promise<RunWithSummary> {
  return fetchJson(`/api/runs/${id}`, {headers: clientHeaders()});
}

/**
 * Starts generation for a run, optionally forcing a provider.
 *
 * @param id Run identifier.
 * @param body Optional provider override.
 * @returns The run id and its new status.
 */
export function startRun(
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

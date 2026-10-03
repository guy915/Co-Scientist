import type {Run, RunWithSummary, QaSource, RunMessage} from './wire_runs';
import type {RunFocus, RunTier, RunStatus} from './wire_common';
import type {
  ClaimEvidenceRow,
  Evidence,
  Hypothesis,
  HypothesisOutcome,
  HypothesisOutcomeInput,
  MatchRow,
  Review,
  SafetyDecision,
} from './wire_science';
import type {Report, SharedGoalReport} from './wire_reports';
import type {ChatSummary, Interview} from './wire_interviews';
import {
  clearAccessToken,
  getAccessToken,
  getClientId,
  getStoredApiKey,
  getStoredApiProvider,
  getStoredModel,
} from '@/lib/client_id';

export type * from './wire_common';
export type * from './wire_runs';
export type * from './wire_science';
export type * from './wire_interviews';
export type * from './wire_reports';

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

/** A durable owner-authorized request to refine one outcome's parent. */
export interface OutcomeRefinementAction {
  action_id: string;
  run_id: string;
  outcome_id: string;
  hypothesis_id: string;
  task_idempotency_key: string;
  checkpoint_seq: number;
  context_codepoints: number;
  status: string;
  child_hypothesis_id: string | null;
  created_at: number;
  replayed: boolean;
}

/** One saved Supervisor decision in the durable allocation ledger. */
export interface SupervisorAllocation {
  id: number;
  run_id: string;
  seq: number;
  iteration: number;
  task_type: string;
  status: string;
  reason: string;
  planner_reason: string | null;
  priority: number | null;
  termination_reason: string | null;
  created_at: number;
}

/** The Supervisor plan snapshot, absent until the first checkpoint commits. */
export interface SupervisorPlanRecord {
  run_id: string;
  plan: Record<string, unknown>;
  orchestrator_state: Record<string, unknown>;
  decision_provenance: string | null;
  termination_reason: string | null;
  created_at: number;
  updated_at: number;
}

/** The persisted plan and append-ordered allocation rows for one run. */
export interface SupervisorPlanResponse {
  plan: SupervisorPlanRecord | null;
  allocations: SupervisorAllocation[];
}

/** Most run collections use their path segment as the response key. */
function getRunList<T>(id: string, key: string): Promise<T[]> {
  return fetchField<string, T[]>(`/api/runs/${id}/${key}`, key, {
    headers: clientHeaders(),
  });
}

export function getHypotheses(id: string): Promise<Hypothesis[]> {
  return getRunList<Hypothesis>(id, 'hypotheses');
}

export function getEvidence(id: string): Promise<Evidence[]> {
  return getRunList<Evidence>(id, 'evidence');
}

export function getMatches(id: string): Promise<MatchRow[]> {
  return getRunList<MatchRow>(id, 'matches');
}

export function getReviews(id: string): Promise<Review[]> {
  return getRunList<Review>(id, 'reviews');
}

/** Fetch the versioned safety audit trail for a run. */
export function getSafety(id: string): Promise<SafetyDecision[]> {
  return getRunList<SafetyDecision>(id, 'safety');
}

/** This collection's response key differs from its path segment. */
export function getClaimEvidence(id: string): Promise<ClaimEvidenceRow[]> {
  return fetchField<'claim_evidence', ClaimEvidenceRow[]>(
    `/api/runs/${id}/claim-evidence`,
    'claim_evidence',
    {headers: clientHeaders()},
  );
}

/** Fetch the persisted Supervisor plan and ordered allocation ledger. */
export function getSupervisorPlan(id: string): Promise<SupervisorPlanResponse> {
  return fetchJson(`/api/runs/${id}/supervisor-plan`, {
    headers: clientHeaders(),
  });
}

/** Fetch scientist-recorded empirical outcomes for a run. */
export function getHypothesisOutcomes(
  id: string,
): Promise<HypothesisOutcome[]> {
  return getRunList<HypothesisOutcome>(id, 'outcomes');
}

/** Append a scientist-recorded observation to one hypothesis. */
export function addHypothesisOutcome(
  runId: string,
  hypothesisId: string,
  input: HypothesisOutcomeInput,
): Promise<HypothesisOutcome> {
  return fetchJson(
    `/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes`,
    jsonRequest(input, true),
  );
}

/** Fetch one existing outcome refinement action for its owner. */
export function getHypothesisOutcomeRefinement(
  runId: string,
  hypothesisId: string,
  outcomeId: string,
): Promise<OutcomeRefinementAction> {
  return fetchJson(
    `/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/${outcomeId}/refine`,
    {headers: clientHeaders()},
  );
}

/** Request or replay one owner's outcome-to-parent refinement intent. */
export function requestHypothesisOutcomeRefinement(
  runId: string,
  hypothesisId: string,
  outcomeId: string,
): Promise<OutcomeRefinementAction> {
  const idempotencyKey = `outcome-refinement:${runId}:${hypothesisId}:${outcomeId}`;
  return fetchJson(
    `/api/runs/${runId}/hypotheses/${hypothesisId}/outcomes/${outcomeId}/refine`,
    {
      method: 'POST',
      headers: {
        ...clientHeaders(),
        'Idempotency-Key': idempotencyKey,
      },
    },
  );
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

/** A 404 means the report has not been generated yet. */
export async function getReport(id: string): Promise<Report | null> {
  const res = await fetchWithSession(`${API_BASE_URL}/api/runs/${id}/report`, {
    headers: clientHeaders(),
  });
  if (res.status === 404) return null; // no report yet, not an error
  return parseJson<Report>(res);
}

/** Loads a public read-only Goal Report without a client ownership header. */
export function getSharedGoalReport(token: string): Promise<SharedGoalReport> {
  return fetchJson(`/api/shared/${token}`);
}

/** A frame of a streamed interview turn. */
type InterviewFrame =
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'interview'; interview: Interview}
  | {type: 'error'; detail: string};

export interface InterviewSinks {
  /** Receives each chain-of-thought fragment as it arrives. */
  onReasoning?: (fragment: string) => void;
  /** Receives each fragment of the answer's prose as it is written. */
  onProse?: (fragment: string) => void;
}

/** Relay live fragments and return the final durable interview snapshot. */
async function streamInterviewTurn(
  path: string,
  body: unknown,
  sinks: InterviewSinks = {},
  method = 'POST',
  signal?: AbortSignal,
): Promise<Interview> {
  let interview: Interview | undefined;
  for await (const frame of streamJson<InterviewFrame>(
    path,
    body,
    signal,
    method,
  )) {
    switch (frame.type) {
      case 'interview':
        interview = frame.interview;
        break;
      case 'error':
        throw new Error(frame.detail);
      case 'reasoning':
        sinks.onReasoning?.(frame.content);
        break;
      case 'chunk':
        sinks.onProse?.(frame.content);
    }
  }
  if (!interview) {
    throw new Error('The Agent could not continue the interview.');
  }
  return interview;
}

/** Starts a durable model-driven research-goal interview. */
export function createInterview(
  researchChallenge: string,
  sinks?: InterviewSinks,
  documentIds: string[] = [],
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    '/api/interviews',
    {
      research_challenge: researchChallenge,
      document_ids: documentIds,
    },
    sinks,
    'POST',
    signal,
  );
}

/** Staged documents shape this turn while the Agent derives its answer. */
export function addInterviewTurn(
  interviewId: string,
  content: string,
  sinks?: InterviewSinks,
  documentIds: string[] = [],
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns`,
    {content, document_ids: documentIds},
    sinks,
    'POST',
    signal,
  );
}

/** Replace a scientist turn and discard/rederive everything after it. */
export function editInterviewTurn(
  interviewId: string,
  turnId: number,
  content: string,
  sinks?: InterviewSinks,
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}`,
    {content},
    sinks,
    'PUT',
    signal,
  );
}

/** Discards one Agent turn and answers the same prompt again. */
export function retryInterviewTurn(
  interviewId: string,
  turnId: number,
  sinks?: InterviewSinks,
  signal?: AbortSignal,
): Promise<Interview> {
  return streamInterviewTurn(
    `/api/interviews/${interviewId}/turns/${turnId}/retry`,
    {},
    sinks,
    'POST',
    signal,
  );
}

/** Sidebar summaries omit transcripts; reopen a conversation by id. */
export function listInterviews(): Promise<ChatSummary[]> {
  return fetchJson('/api/interviews', {headers: clientHeaders()});
}

/** Reloads a durable interview for resume. */
export function getInterview(interviewId: string): Promise<Interview> {
  return fetchJson(`/api/interviews/${interviewId}`, {
    headers: clientHeaders(),
  });
}

/** Persist scientist edits to the four verified fields. */
export function editInterviewFields(
  interviewId: string,
  fields: Interview['fields'],
): Promise<Interview> {
  return fetchJson(`/api/interviews/${interviewId}/fields`, {
    ...jsonRequest(fields, true),
    method: 'PUT',
  });
}

export type {QaSource, RunMessage} from './wire_runs';

/** Where a streamed Q&A answer's three live channels go. */
export interface QaSinks {
  /** The evidence manifest, delivered once before any chunk arrives. */
  onSources?: (sources: QaSource[]) => void;
  /** Receives each fragment of the model's chain of thought, before the
   * answer's own prose starts arriving. */
  onReasoning?: (fragment: string) => void;
  /** Receives each fragment of the answer's prose as it is written. */
  onChunk?: (fragment: string) => void;
}

type AskFrame =
  | {type: 'sources'; sources: QaSource[]}
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'done'; question_id: number}
  | {type: 'error'; message: string};

/** Stream an answer; aborted partial answers are never persisted. */
export async function askRunQuestion(
  runId: string,
  question: string,
  sinks: QaSinks = {},
  signal?: AbortSignal,
): Promise<number | undefined> {
  let questionId: number | undefined;
  for await (const frame of streamJson<AskFrame>(
    `/api/runs/${runId}/messages/ask`,
    {question},
    signal,
  )) {
    switch (frame.type) {
      case 'sources':
        sinks.onSources?.(frame.sources);
        break;
      case 'reasoning':
        sinks.onReasoning?.(frame.content);
        break;
      case 'chunk':
        sinks.onChunk?.(frame.content);
        break;
      case 'done':
        questionId = frame.question_id;
        break;
      case 'error':
        throw new Error(frame.message);
    }
  }
  return questionId;
}

/** Reload chronological steering and Q&A messages; callers filter by kind. */
export function getRunMessages(runId: string): Promise<RunMessage[]> {
  return fetchField(`/api/runs/${runId}/messages`, 'messages', {
    headers: clientHeaders(),
  });
}

export type StartAnnouncementSinks = Pick<QaSinks, 'onReasoning' | 'onChunk'>;

export interface StartAnnouncement {
  /** True when the server used its deterministic announcement. */
  fallback: boolean;
}

type StartFrame =
  | {type: 'reasoning'; content: string}
  | {type: 'chunk'; content: string}
  | {type: 'done'; prompt_id: number; fallback: boolean};

/** Announce an already-started run; failure here cannot change its status. */
export async function announceRunStart(
  runId: string,
  prompt: string,
  sinks: StartAnnouncementSinks = {},
  signal?: AbortSignal,
): Promise<StartAnnouncement | null> {
  let outcome: StartAnnouncement | null = null;
  for await (const frame of streamJson<StartFrame>(
    `/api/runs/${runId}/messages/started`,
    {prompt},
    signal,
  )) {
    if (frame.type === 'done') {
      outcome = {fallback: frame.fallback};
    } else {
      const sink =
        frame.type === 'reasoning' ? sinks.onReasoning : sinks.onChunk;
      sink?.(frame.content);
    }
  }
  return outcome;
}

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

/** Exchange a configured researcher invite code for a signed session. */
export function exchangeAccessCode(
  accessCode: string,
): Promise<{access_token: string; researcher_id: string; expires_in: number}> {
  return fetchJson(
    '/api/auth/exchange',
    jsonRequest({access_code: accessCode}),
  );
}

/** Researcher sessions take precedence over anonymous browser identities. */
export function clientHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token
    ? {Authorization: `Bearer ${token}`}
    : {'X-Client-ID': getClientId()};
}

/** BYOK credentials and model choices travel only in request headers. */
export function byokHeaders(): Record<string, string> {
  const apiKey = getStoredApiKey();
  if (!apiKey) return {};
  const worker = getStoredModel('worker');
  const supervisor = getStoredModel('supervisor');
  return {
    'X-LLM-API-Key': apiKey,
    'X-LLM-Provider': getStoredApiProvider(),
    // Omitted when unset: the backend then runs the provider's default.
    ...(worker ? {'X-LLM-Model': worker} : {}),
    ...(supervisor ? {'X-LLM-Supervisor-Model': supervisor} : {}),
  };
}

/** Keeps status available to callers that distinguish conflicts/failures. */
export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

async function responseErrorMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => res.statusText);
  if (res.status === 500 && !text.trim()) return 'API unavailable';
  // Usage-limit refusals carry reader-facing instructions in `detail`.
  if (res.status === 403 || res.status === 429) {
    try {
      const detail: unknown = (JSON.parse(text) as {detail?: unknown}).detail;
      if (typeof detail === 'string' && detail) return detail;
    } catch {
      // A non-JSON response keeps the ordinary status/body message.
    }
  }
  return `${res.status} ${text || res.statusText}`;
}

/**
 * Fetch with session expiry tied to the credentials actually sent. A delayed
 * anonymous request or a request using an older token must never erase a
 * session established while it was in flight. JSON, downloads, and streams
 * share this transport so they apply the same rule.
 */
export async function fetchWithSession(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const authorization = new Headers(init?.headers).get('Authorization');
  const res = await fetch(url, init);
  const currentToken = getAccessToken();
  if (
    res.status === 401 &&
    currentToken &&
    authorization === `Bearer ${currentToken}`
  ) {
    clearAccessToken();
  }
  return res;
}

export async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new HttpError(await responseErrorMessage(res), res.status);
  }
  return (await res.json()) as T;
}

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetchWithSession(`${API_BASE_URL}${path}`, init);
  return parseJson<T>(res);
}

/** Unwrap a named field of a JSON response envelope. */
export async function fetchField<K extends string, T>(
  path: string,
  field: K,
  init?: RequestInit,
): Promise<T> {
  const data = await fetchJson<Record<K, T>>(path, init);
  return data[field];
}

/** Public endpoints omit identity; scoped endpoints opt in. */
export function jsonRequest(
  body: unknown,
  includeClientId = false,
): RequestInit & {headers: Record<string, string>} {
  return {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(includeClientId ? clientHeaders() : {}),
    },
    body: JSON.stringify(body),
  };
}

/** Parse complete SSE frames while retaining a trailing partial frame. */
export async function* readSseFrames<T>(res: Response): AsyncGenerator<T> {
  if (!res.ok || !res.body) throw new Error(await responseErrorMessage(res));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  for (;;) {
    const {done, value} = await reader.read();
    pending += decoder.decode(value, {stream: !done});
    const frames = pending.split('\n\n');
    pending = frames.pop() || '';
    for (const frame of frames) {
      const data = frame
        .split('\n')
        .find(line => line.startsWith('data: '))
        ?.slice(6);
      if (data) yield JSON.parse(data) as T;
    }
    if (done) break;
  }
}

/** Stream a model-backed JSON request with caller identity and BYOK headers. */
export async function* streamJson<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
  method = 'POST',
): AsyncGenerator<T> {
  const init = jsonRequest(body, true);
  const res = await fetchWithSession(`${API_BASE_URL}${path}`, {
    ...init,
    method,
    signal,
    headers: {...init.headers, ...byokHeaders()},
  });
  yield* readSseFrames<T>(res);
}

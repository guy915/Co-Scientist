import {
  appendChatMessage,
  emitDiagnosticEvent,
} from './chat_session_transcript';
import {
  announceRunStart,
  isDraftStatus,
  isFailureStatus,
  cancelRun,
  createRun,
  getRun,
  isCancelledStatus,
  isStartedStatus,
  retiresStartIntent,
  startRun,
  type Run,
} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {RUNS_CHANGED_EVENT} from '../dom_events';
import type {StartedSession} from '../pages/chat_timeline_run_spec_card';
import {announceChatsChanged} from './history_context';
import {
  type ExecuteStartDeps,
  type HandlerDeps,
  type SpecStage,
} from './use_chat_session';
import {beginTurnAbort, isAbortError} from './chat_session_transcript';
import {interviewToRunSpec} from '../run_spec';
import {
  getStoredApiKey,
  getStoredApiProvider,
  getAccessToken,
  getClientId,
  makePrefixedId,
} from '@/lib/client_id';
import {
  recoverySpecForRun,
  type LinkedRunTarget,
  type PendingRunCreatePayload,
} from '../run_spec';

/**
 * The scientist's start request, persisted with the Agent's announcement.
 */
export const START_RESEARCH_PROMPT = 'Start research';

// Resolves and starts the run tied to this explicit action.
interface StartResult {
  session: StartedSession;
  shouldAnnounce: boolean;
}

type StartDeps = StartRecoveryDeps;

function validateStartTarget(
  target: ResolvedStartTarget,
  deps: Pick<ExecuteStartDeps, 'setDraft' | 'setConfirmed' | 'stageToStart'>,
): ResolvedStartTarget {
  if (isFailureStatus(target.status)) {
    deps.setConfirmed(null);
    deps.setDraft(deps.stageToStart);
    throw runOutcomeError(target.status);
  }
  return target;
}

async function executeStart(deps: StartDeps): Promise<StartResult> {
  const chatId = deps.stageToStart.spec.interviewId;
  const target = validateStartTarget(await resolveStartTarget(deps), deps);
  const stage = target.stage ?? deps.stageToStart;
  let shouldAnnounce = isDraftStatus(target.status);

  if (shouldAnnounce) {
    appendChatMessage(deps.setMessages, {
      role: 'user',
      content: START_RESEARCH_PROMPT,
    });
  }
  // Keep the completed interview turn with its confirmed plan.
  deps.setConfirmed(stage);
  deps.setDraft(null);
  if (shouldAnnounce) {
    const disposition = await startOrSettle(
      target.runId,
      chatId,
      target.intent,
      deps,
    );
    shouldAnnounce = disposition === 'started';
  }
  const session: StartedSession = {
    id: target.runId,
    title: conciseTitle(stage.spec.goal),
    at: Date.now() / 1000,
    // The card waits only while this request is actually being announced.
    announcing: shouldAnnounce,
  };
  deps.setPendingAttachments([]);
  // The server closes the interview when its run starts.
  deps.setInput('');
  deps.setStartedSession(session);
  await deps.reloadHistory();
  // Refresh the home cards and sidebar linked to this chat.
  window.dispatchEvent(new Event(RUNS_CHANGED_EVENT));
  announceChatsChanged();
  return {session, shouldAnnounce};
}

// Merges announcement fragments into the mounted session card.
function appendAnnouncement(
  setStartedSession: ExecuteStartDeps['setStartedSession'],
  patch: 'intro' | 'reasoning',
  fragment: string,
): void {
  setStartedSession(current =>
    current
      ? {...current, [patch]: (current[patch] ?? '') + fragment}
      : current,
  );
}

/** Streams the Agent's reply after a newly confirmed start. */
async function announceStart(
  deps: ExecuteStartDeps & Pick<HandlerDeps, 'turnAbortRef'>,
  runId: string,
): Promise<void> {
  deps.setStartedSession(current =>
    current ? {...current, announcing: true} : current,
  );
  // The composer's Stop control keys off this, so a provider that hangs
  // mid-announcement is escapable rather than minutes of blocked composer.
  deps.setIsAwaitingAgent(true);
  try {
    const outcome = await announceRunStart(
      runId,
      START_RESEARCH_PROMPT,
      {
        onReasoning: fragment =>
          appendAnnouncement(deps.setStartedSession, 'reasoning', fragment),
        onChunk: fragment =>
          appendAnnouncement(deps.setStartedSession, 'intro', fragment),
      },
      beginTurnAbort(deps),
    );
    emitDiagnosticEvent({
      stage: 'CHAT',
      runId,
      payload: {
        event: 'start_announced',
        fallback: Boolean(outcome?.fallback),
      },
    });
  } catch (error) {
    const stopped = isAbortError(error);
    emitDiagnosticEvent({
      stage: 'CHAT',
      runId,
      payload: {
        event: stopped
          ? 'start_announcement_stopped'
          : 'start_announcement_failed',
      },
    });
    // A reply that ended early persisted nothing server-side, so reopening
    // this chat shows the standby copy. Drop whatever fragment arrived so
    // the card on screen says the same thing rather than keeping half a
    // sentence the reload will not have.
    deps.setStartedSession(current =>
      current ? {...current, intro: undefined, reasoning: undefined} : current,
    );
  } finally {
    deps.turnAbortRef.current = null;
    // An empty intro settles to the standby copy the moment this clears.
    deps.setStartedSession(current =>
      current ? {...current, announcing: false} : current,
    );
    deps.setIsAwaitingAgent(false);
  }
}

// Runs create/start and records its lifecycle diagnostics.
async function startDraftRun(
  deps: StartDeps &
    Pick<HandlerDeps, 'turnAbortRef'> & {
      setError: (message: string) => void;
    },
): Promise<void> {
  const {setError} = deps;
  emitDiagnosticEvent({
    stage: 'LIFECYCLE',
    payload: {event: 'start_requested'},
  });
  try {
    const outcome = await executeStart(deps);
    const {session} = outcome;
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      runId: session.id,
      payload: {event: 'start_queued', run_id: session.id},
    });
    // Inside the same try, and inside promoteDraftToRun's `isStarting`
    // window: a question submitted mid-announcement would route to the run's
    // Q&A endpoint and write into the same session state this stream is
    // filling. The Stop control reaches it through `turnAbortRef`, so a
    // provider that hangs is not a composer blocked for minutes.
    if (outcome.shouldAnnounce) await announceStart(deps, session.id);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    setError(message);
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      level: 'error',
      payload: {event: 'start_failed', message},
    });
  }
}

/** Starts or recovers a run from the explicit Start action. */
export async function promoteDraftToRun(deps: HandlerDeps): Promise<void> {
  const stageToStart = deps.draft ?? linkedInterviewStage(deps.interview);
  if (!stageToStart || deps.startedSession) return;
  // Snapshot the draft up front so state changes during the awaits below
  // can't swap the stage out from under this start attempt.
  deps.setIsStarting(true);
  deps.setError(null);
  deps.setToast(null);
  try {
    await startDraftRun({...deps, stageToStart});
  } finally {
    deps.setIsStarting(false);
  }
}

function linkedInterviewStage(
  interview: HandlerDeps['interview'],
): HandlerDeps['draft'] {
  if (!interview?.run_id) return null;
  const closing = completedInterviewClosing(interview);
  return closing ? stageFromClosing(interview, closing) : null;
}

function completedInterviewClosing(
  interview: NonNullable<HandlerDeps['interview']>,
) {
  if (interview.status !== 'completed') return null;
  const closing = interview.turns.at(-1);
  return closing?.role === 'agent' ? closing : null;
}

function stageFromClosing(
  interview: NonNullable<HandlerDeps['interview']>,
  closing: NonNullable<ReturnType<typeof completedInterviewClosing>>,
): NonNullable<HandlerDeps['draft']> {
  return {
    spec: interviewToRunSpec(interview),
    createdAt: closing.created_at,
    intro: closing.content,
    reasoning: closing.reasoning ?? undefined,
    turnId: closing.id,
    fallback: closing.fallback || undefined,
  };
}

const STORAGE_PREFIX = 'co_scientist_pending_run_create:';

interface StoredIntent {
  version: 1;
  key: string;
  ownerFingerprint: string;
  byokFingerprint: string;
  payloadJson: string;
  createdRunId?: string;
}

export interface PendingCreateIntent<
  T extends Record<string, unknown> = Record<string, unknown>,
> {
  key: string;
  payload: T;
  createdRunId?: string;
}

/** Returns one exact, owner- and credential-scoped create request per chat. */
export async function getPendingCreateIntent<T extends Record<string, unknown>>(
  chatId: string,
  payload: T,
): Promise<{key: string; payload: T; createdRunId?: string}> {
  const storageKey = `${STORAGE_PREFIX}${encodeURIComponent(chatId)}`;
  const payloadJson = JSON.stringify(payload);
  const [ownerFingerprint, byokFingerprint] = await Promise.all([
    fingerprint(ownerMaterial()),
    fingerprint(credentialMaterial()),
  ]);

  const stored = readIntent(storageKey);
  if (matchesIntent(stored, ownerFingerprint, byokFingerprint, payloadJson)) {
    return {
      key: stored.key,
      payload: JSON.parse(stored.payloadJson) as T,
      createdRunId: stored.createdRunId,
    };
  }

  const intent: StoredIntent = {
    version: 1,
    key: makePrefixedId('run-create'),
    ownerFingerprint,
    byokFingerprint,
    payloadJson,
  };
  sessionStorage.setItem(storageKey, JSON.stringify(intent));
  return {key: intent.key, payload: JSON.parse(payloadJson) as T};
}

/** Reads the exact pending request for this chat and owner without rebuilding it. */
export async function readPendingCreateIntent<
  T extends Record<string, unknown> = Record<string, unknown>,
>(chatId: string): Promise<PendingCreateIntent<T> | undefined> {
  const [ownerFingerprint, byokFingerprint] = await Promise.all([
    fingerprint(ownerMaterial()),
    fingerprint(credentialMaterial()),
  ]);
  const intent = readIntent(intentStorageKey(chatId));
  if (!intent || !matchesOwner(intent, ownerFingerprint, byokFingerprint)) {
    return undefined;
  }

  return publicIntent<T>(intent);
}

function matchesOwner(
  intent: StoredIntent,
  ownerFingerprint: string,
  byokFingerprint: string,
): boolean {
  return (
    intent.ownerFingerprint === ownerFingerprint &&
    intent.byokFingerprint === byokFingerprint
  );
}

function publicIntent<T extends Record<string, unknown>>(
  intent: StoredIntent,
): PendingCreateIntent<T> | undefined {
  try {
    const payload: unknown = JSON.parse(intent.payloadJson);
    if (!isRecord(payload) || Array.isArray(payload)) return undefined;
    return {
      key: intent.key,
      payload: payload as T,
      createdRunId: intent.createdRunId,
    };
  } catch {
    return undefined;
  }
}

/** Records the known run without changing the request's idempotency key. */
export function rememberPendingCreateRun(
  chatId: string,
  key: string,
  runId: string,
): void {
  const storageKey = intentStorageKey(chatId);
  const intent = readIntent(storageKey);
  if (!intent || intent.key !== key) return;
  sessionStorage.setItem(
    storageKey,
    JSON.stringify({...intent, createdRunId: runId}),
  );
}

/** Removes only the intent whose request key has reached a settled outcome. */
export function retirePendingCreateIntent(chatId: string, key: string): void {
  const storageKey = intentStorageKey(chatId);
  if (readIntent(storageKey)?.key === key) {
    sessionStorage.removeItem(storageKey);
  }
}

function intentStorageKey(chatId: string): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(chatId)}`;
}

function ownerMaterial(): string {
  const token = getAccessToken();
  return token ? `researcher:${token}` : `client:${getClientId()}`;
}

function credentialMaterial(): string {
  const apiKey = getStoredApiKey();
  return apiKey ? `${getStoredApiProvider()}\u0000${apiKey}` : '';
}

function matchesIntent(
  intent: StoredIntent | undefined,
  ownerFingerprint: string,
  byokFingerprint: string,
  payloadJson: string,
): intent is StoredIntent {
  return Boolean(
    intent &&
    intent.ownerFingerprint === ownerFingerprint &&
    intent.byokFingerprint === byokFingerprint &&
    intent.payloadJson === payloadJson,
  );
}

function readIntent(key: string): StoredIntent | undefined {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    return isStoredIntent(parsed) ? parsed : undefined;
  } catch {
    // A damaged session entry is replaced by a fresh request intent.
  }
  return undefined;
}

function isStoredIntent(value: unknown): value is StoredIntent {
  if (!isRecord(value) || value.version !== 1) return false;
  if (
    value.createdRunId !== undefined &&
    typeof value.createdRunId !== 'string'
  ) {
    return false;
  }
  const stringFields = [
    'key',
    'ownerFingerprint',
    'byokFingerprint',
    'payloadJson',
  ] as const;
  return stringFields.every(field => typeof value[field] === 'string');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

async function fingerprint(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), byte =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
}

type SettleDeps = Pick<
  ExecuteStartDeps,
  'setDraft' | 'setConfirmed' | 'stageToStart'
>;
export type StartRecoveryDeps = ExecuteStartDeps &
  Pick<HandlerDeps, 'draft' | 'interview'>;
type CreateRunPayload = Parameters<typeof createRun>[0];
type StartDisposition = 'started' | 'already-started';

export interface ResolvedStartTarget {
  runId: string;
  status: string;
  intent?: PendingCreateIntent;
  stage?: SpecStage;
  run: Run;
}

function buildCreateRunPayload(deps: ExecuteStartDeps): CreateRunPayload {
  const spec = deps.stageToStart.spec;
  return {
    research_goal: spec.goal,
    interview_id: spec.interviewId,
    requirements: spec.requirements,
    attributes: spec.attributes,
    criteria: spec.criteria,
    focus: spec.focus,
    tier: spec.tier,
    notify_on_completion: Boolean(spec.notifyOnCompletion),
    completion_email: spec.notifyOnCompletion
      ? spec.completionEmail
      : undefined,
    enable_literature_review: deps.pubmedEnabled,
    enable_web_search: deps.webSearchEnabled,
    // Creation copies staged documents into the run's corpus.
    document_ids: deps.pendingAttachments.map(document => document.id),
  };
}

export async function startOrSettle(
  runId: string,
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
  deps: SettleDeps,
): Promise<StartDisposition> {
  try {
    await startRun(runId);
    retireIntent(chatId, intent);
    return 'started';
  } catch (error) {
    return resolveStartError(runId, chatId, intent, deps, error);
  }
}

async function resolveStartError(
  runId: string,
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
  deps: SettleDeps,
  error: unknown,
): Promise<StartDisposition> {
  const status = await readRunStatus(runId);
  if (isStartedStatus(status)) {
    retireIntent(chatId, intent);
    return 'already-started';
  }
  if (isDraftStatus(status)) {
    return resolveDraftAfterFailedStart(runId, chatId, intent, deps, error);
  }
  if (isCancelledStatus(status)) retireIntent(chatId, intent);
  restoreDraft(deps);
  throw startErrorForStatus(status) ?? error;
}

async function resolveDraftAfterFailedStart(
  runId: string,
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
  deps: SettleDeps,
  error: unknown,
): Promise<StartDisposition> {
  const status = await cancelAndReadStatus(runId);
  if (isCancelledStatus(status)) retireIntent(chatId, intent);
  if (isStartedStatus(status)) {
    retireIntent(chatId, intent);
    return 'already-started';
  }
  restoreDraft(deps);
  throw error;
}

async function cancelAndReadStatus(runId: string): Promise<string | undefined> {
  const cancellation = await cancelRun(runId).catch(() => undefined);
  if (isCancelledStatus(cancellation?.status)) return 'cancelled';
  // A lost cancel response may mean the run started between the requests.
  return readRunStatus(runId);
}

export function retireIntent(
  chatId: string | undefined,
  intent: PendingCreateIntent | undefined,
): void {
  if (chatId && intent) retirePendingCreateIntent(chatId, intent.key);
}

async function readRunStatus(runId: string): Promise<string | undefined> {
  try {
    return (await getRun(runId)).status;
  } catch {
    return undefined;
  }
}

function restoreDraft(deps: SettleDeps): void {
  deps.setConfirmed(null);
  deps.setDraft(deps.stageToStart);
}

export function runOutcomeError(status: string): Error {
  return new Error(
    `The existing run is ${status}. Open its details to review it before retrying.`,
  );
}

function startErrorForStatus(status: string | undefined): Error | undefined {
  if (isFailureStatus(status)) return runOutcomeError(status);
}

async function readStartIntent(
  chatId: string | undefined,
): Promise<PendingCreateIntent<CreateRunPayload> | undefined> {
  if (!chatId) return undefined;
  return readPendingCreateIntent<CreateRunPayload>(chatId);
}

function linkedRunId(
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  interview: HandlerDeps['interview'],
): string | null | undefined {
  if (intent?.createdRunId) return intent.createdRunId;
  return interview?.run_id;
}

export async function resolveStartTarget(
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget> {
  const payload = buildCreateRunPayload(deps);
  const chatId = payload.interview_id;
  const intent = await readStartIntent(chatId);
  const linked = await getLinkedRun(
    linkedRunId(intent, deps.interview),
    chatId,
    intent,
    deps,
  );
  if (linked) {
    if (isCancelledStatus(linked.status)) {
      return createStartTarget(payload, chatId, undefined);
    }
    return linked;
  }
  if (intent && !sameCreatePayload(intent.payload, payload)) {
    return resolveChangedPendingIntent(payload, chatId, intent, deps);
  }
  return createStartTarget(payload, chatId, intent);
}

async function resolveChangedPendingIntent(
  payload: CreateRunPayload,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload>,
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget> {
  const previous = await postCreate(payload, chatId, intent);
  const settled = await cancelUnstartedDraft(previous, deps);
  if (isCancelledStatus(settled.status)) {
    return createAfterCancelledReceipt(payload, chatId, settled);
  }
  if (isStartedStatus(settled.status)) {
    return {
      ...settled,
      stage: stageForRun(deps.stageToStart, deps, settled.run, intent),
    };
  }
  restoreDraft(deps);
  throw startErrorForStatus(settled.status) ?? runOutcomeError(settled.status);
}

async function cancelUnstartedDraft(
  target: ResolvedStartTarget,
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget> {
  if (!isDraftStatus(target.status)) return target;
  const status = await cancelAndReadStatus(target.runId);
  if (retiresStartIntent(status)) {
    return {...target, status};
  }
  restoreDraft(deps);
  throw new Error(
    'The previous setup is still unresolved. Retry after confirming its run was cancelled.',
  );
}

function sameCreatePayload(
  first: CreateRunPayload,
  second: CreateRunPayload,
): boolean {
  return JSON.stringify(first) === JSON.stringify(second);
}

function stageForRun(
  stage: SpecStage,
  deps: StartRecoveryDeps,
  run: Run,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): SpecStage {
  const linked: LinkedRunTarget = {
    chatId: recoveryChatId(deps, intent),
    runId: run.id,
    chat: undefined,
    interview: deps.interview,
  };
  return {
    ...stage,
    spec: recoverySpecForRun(linked, run, recoveryPayload(intent)),
  };
}

function recoveryChatId(
  deps: StartRecoveryDeps,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): string {
  return intent?.payload.interview_id ?? deps.interview?.id ?? '';
}

function recoveryPayload(
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): PendingRunCreatePayload | undefined {
  return intent?.payload as PendingRunCreatePayload | undefined;
}

async function getLinkedRun(
  runId: string | null | undefined,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  deps: StartRecoveryDeps,
): Promise<ResolvedStartTarget | undefined> {
  if (!runId) return undefined;
  intent = rememberLinkedRun(chatId, intent, runId);
  let linkedRun;
  try {
    linkedRun = await getRun(runId);
  } catch (error) {
    restoreDraft(deps);
    throw error;
  }
  if (retiresStartIntent(linkedRun.status)) retireIntent(chatId, intent);
  return {
    runId,
    status: linkedRun.status,
    intent,
    stage: stageForRun(deps.stageToStart, deps, linkedRun, intent),
    run: linkedRun,
  };
}

function rememberLinkedRun(
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  runId: string,
): PendingCreateIntent<CreateRunPayload> | undefined {
  if (!chatId || !intent || intent.createdRunId) return intent;
  rememberPendingCreateRun(chatId, intent.key, runId);
  return {...intent, createdRunId: runId};
}

async function createStartTarget(
  payload: CreateRunPayload,
  chatId: string | undefined,
  pending: PendingCreateIntent<CreateRunPayload> | undefined,
): Promise<ResolvedStartTarget> {
  let intent = pending;
  if (!intent && chatId) intent = await getPendingCreateIntent(chatId, payload);
  const target = await postCreate(payload, chatId, intent);
  if (isCancelledStatus(target.status)) {
    return createAfterCancelledReceipt(payload, chatId, target);
  }
  if (retiresStartIntent(target.status)) retireIntent(chatId, intent);
  return target;
}

async function createAfterCancelledReceipt(
  payload: CreateRunPayload,
  chatId: string | undefined,
  cancelled: ResolvedStartTarget,
): Promise<ResolvedStartTarget> {
  retireIntent(chatId, cancelled.intent);
  const intent = chatId
    ? await getPendingCreateIntent(chatId, payload)
    : undefined;
  const replacement = await postCreate(payload, chatId, intent);
  if (isCancelledStatus(replacement.status)) {
    retireIntent(chatId, replacement.intent);
    throw new Error(
      'The cancelled run was retired. Click Start research again.',
    );
  }
  if (retiresStartIntent(replacement.status)) {
    retireIntent(chatId, replacement.intent);
  }
  return replacement;
}

async function postCreate(
  payload: CreateRunPayload,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): Promise<ResolvedStartTarget> {
  let created;
  try {
    created = await sendCreate(payload, intent);
  } catch (error) {
    retireRejectedIntent(chatId, intent, error);
    throw error;
  }
  rememberCreatedRun(chatId, intent, created.id);
  return {runId: created.id, status: created.status, intent, run: created};
}

async function sendCreate(
  payload: CreateRunPayload,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
) {
  if (intent) return createRun(intent.payload, {idempotencyKey: intent.key});
  return createRun(payload);
}

function retireRejectedIntent(
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  error: unknown,
): void {
  if (chatId && intent && isDefinitiveCreateRejection(error)) {
    retireIntent(chatId, intent);
  }
}

function rememberCreatedRun(
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  runId: string,
): void {
  if (chatId && intent) rememberPendingCreateRun(chatId, intent.key, runId);
}

function isDefinitiveCreateRejection(error: unknown): boolean {
  return (
    error instanceof Error &&
    'status' in error &&
    typeof error.status === 'number' &&
    [400, 401, 403, 404, 413, 415, 422].includes(error.status)
  );
}

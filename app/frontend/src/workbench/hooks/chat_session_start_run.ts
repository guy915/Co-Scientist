import {
  announceRunStart,
  cancelRun,
  createRun,
  getRun,
  startRun,
} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {RUNS_CHANGED_EVENT} from '../dom_events';
import {type StartedSession} from '../pages/chat_timeline_cards';
import {announceChatsChanged} from './chat_history_context';
import {appendChatMessage, emitDiagnosticEvent} from './chat_session_helpers';
import {beginTurnAbort, isAbortError} from './chat_session_handlers_shared';
import {
  getPendingCreateIntent,
  readPendingCreateIntent,
  rememberPendingCreateRun,
  retirePendingCreateIntent,
  type PendingCreateIntent,
} from './chat_session_create_intent';
import {type ExecuteStartDeps, type HandlerDeps} from './chat_session_types';
import {interviewToRunSpec} from '../run_spec';

/**
 * The scientist's start request, persisted with the Agent's announcement.
 */
export const START_RESEARCH_PROMPT = 'Start research';

// Builds the create payload from the confirmed spec and connector toggles.
function buildCreateRunPayload(deps: ExecuteStartDeps) {
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

// The session slice the rollback below writes back.
type SettleDeps = Pick<
  ExecuteStartDeps,
  'setDraft' | 'setConfirmed' | 'stageToStart'
>;

type StartDisposition = 'started' | 'already-started';
type CreateRunPayload = Parameters<typeof createRun>[0];

async function startOrSettle(
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
  if (status === 'draft') {
    return resolveDraftAfterFailedStart(runId, chatId, intent, deps, error);
  }
  if (status === 'cancelled') retireIntent(chatId, intent);
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
  if (status === 'cancelled') retireIntent(chatId, intent);
  if (status && isStartedStatus(status)) {
    retireIntent(chatId, intent);
    return 'already-started';
  }
  restoreDraft(deps);
  throw error;
}

async function cancelAndReadStatus(runId: string): Promise<string | undefined> {
  const cancellation = await cancelRun(runId).catch(() => undefined);
  if (cancellation?.status === 'cancelled') return 'cancelled';
  // A lost cancel response may mean the run started between the requests.
  return readRunStatus(runId);
}

function retireIntent(
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

function isStartedStatus(status: string | undefined): boolean {
  return (
    status === 'queued' ||
    status === 'running' ||
    status === 'synthesizing' ||
    status === 'completed' ||
    status === 'paused'
  );
}

function restoreDraft(deps: SettleDeps): void {
  deps.setConfirmed(null);
  deps.setDraft(deps.stageToStart);
}

// Resolves and starts the run tied to this explicit action.
interface StartResult {
  session: StartedSession;
  shouldAnnounce: boolean;
}

type StartDeps = ExecuteStartDeps & Pick<HandlerDeps, 'draft' | 'interview'>;

interface StartTarget {
  runId: string;
  status: string;
  intent?: PendingCreateIntent;
}

function validateStartTarget(
  target: StartTarget,
  deps: SettleDeps,
): StartTarget {
  if (target.status === 'failed' || target.status === 'blocked') {
    restoreDraft(deps);
    throw runOutcomeError(target.status);
  }
  return target;
}

function runOutcomeError(status: string): Error {
  return new Error(
    `The existing run is ${status}. Open its details to review it before retrying.`,
  );
}

function startErrorForStatus(status: string | undefined): Error | undefined {
  if (status === 'failed' || status === 'blocked') {
    return runOutcomeError(status);
  }
}

function shouldRetireIntent(status: string): boolean {
  return status !== 'draft' && status !== 'failed' && status !== 'blocked';
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

async function resolveStartTarget(deps: StartDeps): Promise<StartTarget> {
  const payload = buildCreateRunPayload(deps);
  const chatId = payload.interview_id;
  const intent = await readStartIntent(chatId);
  const linked = await getLinkedRun(
    linkedRunId(intent, deps.interview),
    chatId,
    intent,
    deps,
  );
  if (!linked) return createStartTarget(payload, chatId, intent);
  if (linked.status === 'cancelled') {
    return createStartTarget(payload, chatId, undefined);
  }
  return linked;
}

async function getLinkedRun(
  runId: string | null | undefined,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
  deps: StartDeps,
): Promise<StartTarget | undefined> {
  if (!runId) return undefined;
  intent = rememberLinkedRun(chatId, intent, runId);
  let linkedRun;
  try {
    linkedRun = await getRun(runId);
  } catch (error) {
    restoreDraft(deps);
    throw error;
  }
  if (shouldRetireIntent(linkedRun.status)) retireIntent(chatId, intent);
  return {runId, status: linkedRun.status, intent};
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
): Promise<StartTarget> {
  let intent = pending;
  if (!intent && chatId) intent = await getPendingCreateIntent(chatId, payload);
  const target = await postCreate(payload, chatId, intent);
  if (target.status === 'cancelled') {
    return createAfterCancelledReceipt(payload, chatId, target);
  }
  if (shouldRetireIntent(target.status)) retireIntent(chatId, intent);
  return target;
}

async function createAfterCancelledReceipt(
  payload: CreateRunPayload,
  chatId: string | undefined,
  cancelled: StartTarget,
): Promise<StartTarget> {
  retireIntent(chatId, cancelled.intent);
  const intent = chatId
    ? await getPendingCreateIntent(chatId, payload)
    : undefined;
  const replacement = await postCreate(payload, chatId, intent);
  if (replacement.status === 'cancelled') {
    retireIntent(chatId, replacement.intent);
    throw new Error(
      'The cancelled run was retired. Click Start research again.',
    );
  }
  if (shouldRetireIntent(replacement.status)) {
    retireIntent(chatId, replacement.intent);
  }
  return replacement;
}

async function postCreate(
  payload: CreateRunPayload,
  chatId: string | undefined,
  intent: PendingCreateIntent<CreateRunPayload> | undefined,
): Promise<StartTarget> {
  // Reopened UI defaults never replace the exact request behind a pending key.
  let created;
  if (intent) {
    created = await createRun(intent.payload, {idempotencyKey: intent.key});
  } else {
    created = await createRun(payload);
  }
  if (chatId && intent) {
    rememberPendingCreateRun(chatId, intent.key, created.id);
  }
  return {runId: created.id, status: created.status, intent};
}

async function executeStart(deps: StartDeps): Promise<StartResult> {
  const chatId = deps.stageToStart.spec.interviewId;
  const target = validateStartTarget(await resolveStartTarget(deps), deps);
  let shouldAnnounce = target.status === 'draft';

  if (shouldAnnounce) {
    appendChatMessage(deps.setMessages, {
      role: 'user',
      content: START_RESEARCH_PROMPT,
    });
  }
  // Keep the completed interview turn with its confirmed plan.
  deps.setConfirmed(deps.stageToStart);
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
    title: conciseTitle(deps.stageToStart.spec.goal),
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

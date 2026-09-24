import {announceRunStart} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {RUNS_CHANGED_EVENT} from '../dom_events';
import {type StartedSession} from '../pages/chat_timeline_cards';
import {announceChatsChanged} from './chat_history_context';
import {appendChatMessage, emitDiagnosticEvent} from './chat_session_helpers';
import {beginTurnAbort, isAbortError} from './chat_session_handlers_shared';
import {type ExecuteStartDeps, type HandlerDeps} from './chat_session_types';
import {interviewToRunSpec} from '../run_spec';
import {
  resolveStartTarget,
  runOutcomeError,
  startOrSettle,
  type ResolvedStartTarget,
  type StartRecoveryDeps,
} from './chat_session_start_recovery';

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
  if (target.status === 'failed' || target.status === 'blocked') {
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
  let shouldAnnounce = target.status === 'draft';

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

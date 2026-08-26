import {announceRunStart, cancelRun, createRun, startRun} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {readStoredAudience} from '../audience_context';
import {RUNS_CHANGED_EVENT} from '../dom_events';
import {type StartedSession} from '../pages/chat_timeline_cards';
import {announceChatsChanged} from './chat_history_context';
import {appendChatMessage, emitDiagnosticEvent} from './chat_session_helpers';
import {beginTurnAbort, isAbortError} from './chat_session_handlers_shared';
import {type ExecuteStartDeps, type HandlerDeps} from './chat_session_types';

/**
 * The scientist's own words for starting the run, sent as the turn the
 * Agent's announcement replies to.
 *
 * The Start control is a shortcut for typing this and pressing send, so it
 * posts the same prompt down the same path rather than decorating the
 * timeline with a message nothing received. It is persisted server-side with
 * the reply, which is also what keeps it on the timeline across a reload --
 * the local-only bubble it replaces did not survive one.
 */
export const START_RESEARCH_PROMPT = 'Start research';

// Builds the POST /api/runs payload from the confirmed spec plus the
// connector toggles.
function buildCreateRunPayload(deps: ExecuteStartDeps) {
  const spec = deps.specToStart;
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
    // The audience persists to localStorage, so this path (which runs outside
    // React and takes its deps as args) reads storage directly rather than
    // threading a hook value through every caller. An unchosen audience sends
    // none, leaving run creation unchanged.
    audience: readStoredAudience() ?? undefined,
    enable_web_search: deps.webSearchEnabled,
    enable_paper_corpus: deps.paperCorpusEnabled,
    // Already uploaded and extracted (see stageDocument), so creation copies
    // them into the run's corpus rather than a second call doing it after
    // the run exists.
    document_ids: deps.pendingAttachments.map(document => document.id),
  };
}

// The session slice the rollback below writes back.
type SettleDeps = Pick<
  ExecuteStartDeps,
  'setDraft' | 'setConfirmed' | 'specToStart' | 'specCreatedAt'
>;

// Starts a just-created run, and settles it if that fails.
//
// Creation and start are two calls, so the window between them is the one
// place run setup can half-succeed. A run created and never started is not
// an error state the durable queue reconciles -- it simply sits, unstarted,
// with nothing naming it. Cancelling it makes the run record the same
// outcome the scientist was told about. A failure to cancel is not worth
// reporting over the failure that caused it: the start error is the one
// the scientist has to act on, so it is the one that propagates.
async function startOrSettle(runId: string, deps: SettleDeps): Promise<void> {
  try {
    await startRun(runId);
  } catch (error) {
    await cancelRun(runId).catch(() => undefined);
    // Put the workspace back where it was before the attempt: the plan is
    // editable again, so a retry re-runs the specification the scientist
    // wrote rather than rebuilding it from the transcript.
    deps.setConfirmed(null);
    deps.setDraft({spec: deps.specToStart, createdAt: deps.specCreatedAt});
    throw error;
  }
}

// Runs the create+start API round trip for a confirmed draft spec and
// applies the resulting state transitions, returning the session that was
// started. Pulled out of startDraftRun so that function's try/catch shell
// only carries diagnostics and error handling.
async function executeStart(deps: ExecuteStartDeps): Promise<StartedSession> {
  // Starting the run reads as the scientist sending the plan into the chat:
  // post the request as a user turn, and let the Agent answer it (see
  // announceStart below) with the session card attached beneath its reply,
  // exactly as the completing interview turn answers with the plan card.
  // Optimistic, like every other submit: the prompt is on screen before the
  // round trip that persists it.
  appendChatMessage(deps.setMessages, {
    role: 'user',
    content: START_RESEARCH_PROMPT,
  });
  const created = await createRun(buildCreateRunPayload(deps));
  const session: StartedSession = {
    id: created.id,
    title: conciseTitle(deps.specToStart.goal),
    at: Date.now() / 1000,
  };
  deps.setConfirmed({spec: deps.specToStart, createdAt: deps.specCreatedAt});
  deps.setDraft(null);
  await startOrSettle(created.id, deps);
  deps.setPendingAttachments([]);
  // The interview is closed server-side from here on, so drop whatever was
  // typed meanwhile (the textarea stays live across the start round trip by
  // design); the composer locks in the same transition (see ComposerSection).
  deps.setInput('');
  deps.setStartedSession(session);
  await deps.reloadHistory();
  // Announce both lists: the home cards show the new run, and the rail's chat
  // row picks up the run it now links to. Both surfaces render outside this
  // page, so a window event is the channel to them.
  window.dispatchEvent(new Event(RUNS_CHANGED_EVENT));
  announceChatsChanged();
  return session;
}

// Merges one streamed fragment of the announcement into the started session
// on screen. A functional update, not a rebuild from a captured value: the
// two channels interleave and both land while the card is already mounted.
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

/**
 * Asks the Agent to answer the scientist's start request, streaming its
 * reply into the session card's lead-in as it is written.
 *
 * Never fails the start. The run is already running by the time this is
 * called, so a provider that cannot be reached, or a reply the scientist
 * stopped, leaves the card showing its standby copy (see
 * STARTED_SESSION_STANDBY_COPY) rather than an error saying the run did not
 * start. The server takes the same view and has no error frame at all.
 */
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

// Runs the create+start API round trip for a confirmed draft spec and applies
// the resulting state transitions and diagnostic events. Takes every value and
// setter it needs as an argument instead of closing over hook state (it calls
// no hooks itself).
async function startDraftRun(
  deps: ExecuteStartDeps &
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
    const session = await executeStart(deps);
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
    await announceStart(deps, session.id);
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

/**
 * Promotes the draft to a real run: createRun (POST /api/runs) then startRun
 * (POST /api/runs/{id}/start).
 *
 * Setup has one committing call. Attachments are staged before this runs
 * (`stageDocument`) and are carried in by creation itself, so a document
 * that cannot be read fails before any run exists. Creation failing leaves
 * nothing behind; start failing settles the run it could not start. Either
 * way the draft stays staged and the failure surfaces via `error`, so a
 * retry re-runs the specification rather than losing it.
 *
 * Takes its dependencies as a single argument instead of closing over hook
 * state.
 */
export async function promoteDraftToRun(deps: HandlerDeps): Promise<void> {
  if (!deps.draft) return;
  // Snapshot the draft up front so state changes during the awaits below
  // can't swap the spec out from under this start attempt.
  const specToStart = deps.draft.spec;
  const specCreatedAt = deps.draft.createdAt;
  deps.setIsStarting(true);
  deps.setError(null);
  deps.setToast(null);
  try {
    await startDraftRun({...deps, specToStart, specCreatedAt});
  } finally {
    deps.setIsStarting(false);
  }
}

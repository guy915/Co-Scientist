import {cancelRun, createRun, startRun} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {readStoredAudience} from '../audience_context';
import {RUNS_CHANGED_EVENT} from '../dom_events';
import {type StartedSession} from '../pages/chat_timeline_cards';
import {announceChatsChanged} from './chat_history_context';
import {appendChatMessage, emitDiagnosticEvent} from './chat_session_helpers';
import {type ExecuteStartDeps, type HandlerDeps} from './chat_session_types';

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
  // post the request as a user turn, then let the open-session card below be
  // the single response. The card carries its own "session started" copy, so a
  // separate assistant acknowledgment bubble would just double the reply.
  appendChatMessage(deps.setMessages, {
    role: 'user',
    content: 'Start research',
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

// Runs the create+start API round trip for a confirmed draft spec and applies
// the resulting state transitions and diagnostic events. Takes every value and
// setter it needs as an argument instead of closing over hook state (it calls
// no hooks itself).
async function startDraftRun(
  deps: ExecuteStartDeps & {setError: (message: string) => void},
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

import {createRun, startRun, uploadRunDocument} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {readStoredAudience} from '../audience_context';
import {RUNS_CHANGED_EVENT} from '../dom_events';
import {type StartedSession} from '../pages/chat_timeline_cards';
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
  };
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
  appendChatMessage(deps.setMessages, 'user', 'Start research');
  const created = await createRun(buildCreateRunPayload(deps));
  const session: StartedSession = {
    id: created.id,
    title: conciseTitle(deps.specToStart.goal),
    at: Date.now() / 1000,
  };
  deps.setConfirmed({spec: deps.specToStart, createdAt: deps.specCreatedAt});
  deps.setDraft(null);
  for (const file of deps.pendingAttachments) {
    await uploadRunDocument(created.id, file);
  }
  await startRun(created.id);
  deps.setPendingAttachments([]);
  deps.setStartedSession(session);
  await deps.reloadHistory();
  // Tell the shell sidebar (which owns a separate history copy) that a new
  // run exists, so it appears immediately instead of only after a reload.
  window.dispatchEvent(new Event(RUNS_CHANGED_EVENT));
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
    setError(err instanceof Error ? err.message : String(err));
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      level: 'error',
      payload: {
        event: 'start_failed',
        message: err instanceof Error ? err.message : String(err),
      },
    });
  }
}

/**
 * Promotes the draft to a real run: createRun (POST /api/runs) then startRun
 * (POST /api/runs/{id}/start). The draft becomes the confirmed spec once
 * creation succeeds; if createRun itself fails the draft stays staged so the
 * user can retry, and either failure surfaces via `error`. Takes its
 * dependencies as a single argument instead of closing over hook state.
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

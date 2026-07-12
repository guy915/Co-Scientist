import {createRun, startRun} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {type StartedSession} from '../pages/chat_timeline_cards';
import {emitDiagnosticEvent} from './chat_session_helpers';
import {type ExecuteStartDeps, type HandlerDeps} from './chat_session_types';

// Runs the create+start API round trip for a confirmed draft spec and
// applies the resulting state transitions, returning the session that was
// started. Pulled out of startDraftRun so that function's try/catch shell
// only carries diagnostics and error handling.
async function executeStart({
  specToStart,
  specCreatedAt,
  pubmedEnabled,
  reloadHistory,
  setConfirmed,
  setDraft,
  setStartedSession,
}: ExecuteStartDeps): Promise<StartedSession> {
  const created = await createRun({
    research_goal: specToStart.goal,
    interview_id: specToStart.interviewId,
    requirements: specToStart.requirements,
    attributes: specToStart.attributes,
    criteria: specToStart.criteria,
    tier: specToStart.tier,
    notify_on_completion: Boolean(specToStart.notifyOnCompletion),
    completion_email: specToStart.notifyOnCompletion
      ? specToStart.completionEmail
      : undefined,
    enable_literature_review: pubmedEnabled,
  });
  const session: StartedSession = {
    id: created.id,
    title: conciseTitle(specToStart.goal),
    at: Date.now() / 1000,
  };
  setConfirmed({spec: specToStart, createdAt: specCreatedAt});
  setDraft(null);
  await startRun(created.id);
  setStartedSession(session);
  await reloadHistory();
  // Tell the shell sidebar (which owns a separate history copy) that a new
  // run exists, so it appears immediately instead of only after a reload.
  window.dispatchEvent(new Event('cosci-runs-changed'));
  return session;
}

// Runs the create+start API round trip for a confirmed draft spec and applies
// the resulting state transitions and diagnostic events. Takes every value and
// setter it needs as an argument instead of closing over hook state (it calls
// no hooks itself).
async function startDraftRun(
  deps: ExecuteStartDeps & {setError: (message: string) => void},
): Promise<void> {
  const {specToStart, setError} = deps;
  emitDiagnosticEvent({
    stage: 'LIFECYCLE',
    run: conciseTitle(specToStart.goal),
    payload: {event: 'start_requested'},
  });
  try {
    const session = await executeStart(deps);
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: session.title,
      level: 'success',
      payload: {event: 'start_queued', run_id: session.id},
    });
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: conciseTitle(specToStart.goal),
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
export async function promoteDraftToRun({
  draft,
  pubmedEnabled,
  reloadHistory,
  setIsStarting,
  setError,
  setToast,
  setConfirmed,
  setDraft,
  setStartedSession,
}: HandlerDeps): Promise<void> {
  if (!draft) return;
  // Snapshot the draft up front so state changes during the awaits below
  // can't swap the spec out from under this start attempt.
  const specToStart = draft.spec;
  const specCreatedAt = draft.createdAt;
  setIsStarting(true);
  setError(null);
  setToast(null);
  try {
    await startDraftRun({
      specToStart,
      specCreatedAt,
      pubmedEnabled,
      reloadHistory,
      setConfirmed,
      setDraft,
      setStartedSession,
      setError,
    });
  } finally {
    setIsStarting(false);
  }
}

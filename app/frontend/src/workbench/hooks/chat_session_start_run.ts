import {createRun, startRun} from '@/api/runs';
import {
  referenceSetupTitle,
  type StartedSession,
} from '../pages/chat_timeline_cards';
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
  setConfirmedSpec,
  setConfirmedSpecCreatedAt,
  setDraftSpec,
  setDraftSpecCreatedAt,
  setStartedSession,
}: ExecuteStartDeps): Promise<StartedSession> {
  const created = await createRun({
    research_goal: specToStart.goal,
    requirements: specToStart.requirements,
    attributes: specToStart.attributes,
    criteria: specToStart.criteria,
    focus: specToStart.focus,
    tier: specToStart.tier,
    enable_literature_review: pubmedEnabled,
  });
  const session: StartedSession = {
    id: created.id,
    title: referenceSetupTitle(specToStart.goal),
    at: Date.now() / 1000,
  };
  setConfirmedSpec(specToStart);
  setConfirmedSpecCreatedAt(specCreatedAt);
  setDraftSpec(null);
  setDraftSpecCreatedAt(null);
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
    run: referenceSetupTitle(specToStart.goal),
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
      run: referenceSetupTitle(specToStart.goal),
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
  draftSpec,
  draftSpecCreatedAt,
  pubmedEnabled,
  reloadHistory,
  setIsStarting,
  setError,
  setToast,
  setConfirmedSpec,
  setConfirmedSpecCreatedAt,
  setDraftSpec,
  setDraftSpecCreatedAt,
  setStartedSession,
}: HandlerDeps): Promise<void> {
  if (!draftSpec) return;
  // Snapshot the draft up front so state changes during the awaits below
  // can't swap the spec out from under this start attempt.
  const specToStart = draftSpec;
  const specCreatedAt = draftSpecCreatedAt ?? Date.now() / 1000;
  setIsStarting(true);
  setError(null);
  setToast(null);
  try {
    await startDraftRun({
      specToStart,
      specCreatedAt,
      pubmedEnabled,
      reloadHistory,
      setConfirmedSpec,
      setConfirmedSpecCreatedAt,
      setDraftSpec,
      setDraftSpecCreatedAt,
      setStartedSession,
      setError,
    });
  } finally {
    setIsStarting(false);
  }
}

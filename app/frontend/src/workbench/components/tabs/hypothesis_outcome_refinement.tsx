import {useState} from 'react';
import {
  requestHypothesisOutcomeRefinement,
  type OutcomeRefinementAction,
} from '@/api/runs';

const STATUS_MESSAGES: Record<
  string,
  (action: OutcomeRefinementAction) => string
> = {
  pending_executor: () =>
    'Refinement request is saved and awaiting worker recovery.',
  queued: () => 'Refinement request is queued.',
  running: () => 'Refinement is running.',
  completed: action =>
    action.child_hypothesis_id
      ? `Follow-up hypothesis ${action.child_hypothesis_id} was created and will pass through the normal gates.`
      : 'A follow-up hypothesis was created and will pass through the normal gates.',
  no_child: () => 'No follow-up hypothesis was created.',
  safety_rejected: () =>
    'The follow-up was rejected by the safety gate; no child was created.',
  failed: () => 'Refinement failed and remains available for owner retry.',
};

/** Discloses, requests and owner-replays one outcome refinement intent. */
export function HypothesisOutcomeRefinement({
  runId,
  hypothesisId,
  outcomeId,
}: {
  runId: string;
  hypothesisId: string;
  outcomeId: string;
}) {
  const [action, setAction] = useState<OutcomeRefinementAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function requestOrReplay() {
    setBusy(true);
    setError(null);
    try {
      setAction(
        await requestHypothesisOutcomeRefinement(
          runId,
          hypothesisId,
          outcomeId,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const statusMessage = refinementStatusMessage(action, busy);
  return (
    <div
      className="grid gap-2 border-t border-cosci-border pt-3"
      aria-busy={busy}
    >
      <p role="note" className="text-sm text-cosci-muted">
        This sends the linked hypothesis and this recorded outcome, with up to
        three source metadata links, to the run’s configured AI model to draft
        one follow-up hypothesis. AI output may be wrong. This action does not
        verify the observation or change existing claims, reviews, safety
        decisions, or ranking.
      </p>
      {statusMessage && (
        <p role="status" className="text-sm text-cosci-muted">
          {statusMessage}
        </p>
      )}
      {error && <p role="alert">Could not request refinement: {error}</p>}
      <button
        type="button"
        onClick={() => void requestOrReplay()}
        disabled={busy}
        className="w-fit rounded-full border border-cosci-border px-4 py-2 text-sm font-medium disabled:opacity-60"
      >
        {refinementButtonLabel(busy, action, error)}
      </button>
    </div>
  );
}

function refinementButtonLabel(
  busy: boolean,
  action: OutcomeRefinementAction | null,
  error: string | null,
): string {
  if (busy)
    return action ? 'Checking refinement…' : 'Sending refinement request…';
  if (error) return 'Retry refinement request';
  if (action) return 'Check or retry refinement';
  return 'Use outcome to refine this hypothesis';
}

function refinementStatusMessage(
  action: OutcomeRefinementAction | null,
  busy: boolean,
): string | null {
  if (busy) return refinementProgressMessage(action);
  return action ? savedRefinementMessage(action) : null;
}

function refinementProgressMessage(
  action: OutcomeRefinementAction | null,
): string {
  return action ? 'Checking refinement status…' : 'Sending refinement request…';
}

function savedRefinementMessage(action: OutcomeRefinementAction): string {
  if (action.replayed) {
    return `The saved refinement request was replayed; no second action was created. Current status: ${action.status}.`;
  }
  return (
    STATUS_MESSAGES[action.status]?.(action) ??
    `Refinement status: ${action.status}.`
  );
}

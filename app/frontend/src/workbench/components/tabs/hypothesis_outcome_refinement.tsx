import {
  type OutcomeRefinementAction,
  getHypothesisOutcomeRefinement,
  HttpError,
  requestHypothesisOutcomeRefinement,
} from '@/api/runs';
import {useCallback, useEffect, useState} from 'react';

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

export function HypothesisOutcomeRefinement({
  runId,
  hypothesisId,
  outcomeId,
  statusOnly = false,
}: {
  runId: string;
  hypothesisId: string;
  outcomeId: string;
  statusOnly?: boolean;
}) {
  const refinement = useHypothesisOutcomeRefinement(
    runId,
    hypothesisId,
    outcomeId,
  );
  if (
    shouldHideStatusOnly(
      statusOnly,
      refinement.checking,
      refinement.action,
      refinement.loadError,
    )
  ) {
    return null;
  }
  return <RefinementActionPanel {...refinement} statusOnly={statusOnly} />;
}

function RefinementActionPanel({
  action,
  checking,
  busy,
  error,
  loadError,
  replayed,
  refreshSavedAction,
  requestOrReplay,
  statusOnly,
}: ReturnType<typeof useHypothesisOutcomeRefinement> & {
  statusOnly: boolean;
}) {
  const statusMessage = refinementStatusMessage(
    action,
    busy,
    replayed,
    checking,
  );
  return (
    <div
      className="grid gap-2 border-t border-cosci-border pt-3"
      aria-busy={checking || busy}
    >
      <RefinementDisclosure
        statusOnly={statusOnly}
        action={action}
        busy={busy}
        error={error}
        loadError={loadError}
      />
      <RefinementStatus message={statusMessage} />
      <RefinementAlert error={error} loadError={loadError} />
      <RefinementActionButton
        loadError={loadError}
        checking={checking}
        busy={busy}
        action={action}
        error={error}
        onRefresh={refreshSavedAction}
        onRequest={requestOrReplay}
      />
    </div>
  );
}

function RefinementDisclosure({
  statusOnly,
  action,
  busy,
  error,
  loadError,
}: {
  statusOnly: boolean;
  action: OutcomeRefinementAction | null;
  busy: boolean;
  error: string | null;
  loadError: boolean;
}) {
  if (
    !shouldShowRefinementDisclosure(statusOnly, action, busy, error, loadError)
  ) {
    return null;
  }
  return (
    <p role="note" className="text-sm text-cosci-muted">
      This sends the linked hypothesis and this recorded outcome, with up to
      three source metadata links, to the run’s configured AI model to draft one
      follow-up hypothesis. AI output may be wrong. This action does not verify
      the observation or change existing claims, reviews, safety decisions, or
      ranking.
    </p>
  );
}

function RefinementStatus({message}: {message: string | null}) {
  if (!message) return null;
  return (
    <p role="status" className="text-sm text-cosci-muted">
      {message}
    </p>
  );
}

function RefinementAlert({
  error,
  loadError,
}: {
  error: string | null;
  loadError: boolean;
}) {
  if (!error) return null;
  return <p role="alert">{refinementErrorMessage(error, loadError)}</p>;
}

function RefinementActionButton({
  loadError,
  checking,
  busy,
  action,
  error,
  onRefresh,
  onRequest,
}: {
  loadError: boolean;
  checking: boolean;
  busy: boolean;
  action: OutcomeRefinementAction | null;
  error: string | null;
  onRefresh: () => Promise<void>;
  onRequest: () => Promise<void>;
}) {
  const label =
    refinementLoadErrorLabel(loadError, checking) ??
    refinementButtonLabel(busy, action, error, checking);
  return (
    <button
      type="button"
      onClick={() =>
        void handleRefinementClick(loadError, onRefresh, onRequest)
      }
      disabled={checking || busy}
      className="w-fit rounded-full border border-cosci-border px-4 py-2 text-sm font-medium disabled:opacity-60"
    >
      {label}
    </button>
  );
}

function refinementButtonLabel(
  busy: boolean,
  action: OutcomeRefinementAction | null,
  error: string | null,
  checking: boolean,
): string {
  if (checking) return 'Checking refinement…';
  if (busy) return refinementProgressMessage(action);
  if (error) return 'Retry refinement request';
  if (action) return 'Check or retry refinement';
  return 'Use outcome to refine this hypothesis';
}

function refinementLoadErrorLabel(
  loadError: boolean,
  checking: boolean,
): string | null {
  if (!loadError) return null;
  return checking ? 'Checking refinement…' : 'Refresh refinement status';
}

function shouldShowRefinementDisclosure(
  statusOnly: boolean,
  action: OutcomeRefinementAction | null,
  busy: boolean,
  error: string | null,
  loadError: boolean,
): boolean {
  return !statusOnly || Boolean(action) || busy || Boolean(error && !loadError);
}

function handleRefinementClick(
  loadError: boolean,
  refreshStatus: () => Promise<void>,
  requestOrReplay: () => Promise<void>,
): Promise<void> {
  if (loadError) return refreshStatus();
  return requestOrReplay();
}

function shouldHideStatusOnly(
  statusOnly: boolean,
  checking: boolean,
  action: OutcomeRefinementAction | null,
  loadError: boolean,
): boolean {
  return statusOnly && !checking && !action && !loadError;
}

function refinementStatusMessage(
  action: OutcomeRefinementAction | null,
  busy: boolean,
  replayed: boolean,
  checking: boolean,
): string | null {
  if (checking) return 'Checking saved refinement status…';
  if (busy) return refinementProgressMessage(action);
  return action ? savedRefinementMessage(action, replayed) : null;
}

function refinementErrorMessage(error: string, loadError: boolean): string {
  const action = loadError
    ? 'Could not load refinement status:'
    : 'Could not request refinement:';
  return `${action} ${error}`;
}

function refinementProgressMessage(
  action: OutcomeRefinementAction | null,
): string {
  return action ? 'Checking refinement status…' : 'Sending refinement request…';
}

function savedRefinementMessage(
  action: OutcomeRefinementAction,
  replayed: boolean,
): string {
  if (replayed) {
    return `The saved refinement request was replayed; no second action was created. Current status: ${action.status}.`;
  }
  return (
    STATUS_MESSAGES[action.status]?.(action) ??
    `Refinement status: ${action.status}.`
  );
}

function useHypothesisOutcomeRefinement(
  runId: string,
  hypothesisId: string,
  outcomeId: string,
) {
  const [action, setAction] = useState<OutcomeRefinementAction | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [replayed, setReplayed] = useState(false);

  const refreshSavedAction = useCallback(async () => {
    setChecking(true);
    setError(null);
    setLoadError(false);
    try {
      setAction(await loadSavedAction(runId, hypothesisId, outcomeId));
      setReplayed(false);
    } catch (err) {
      setError(errorMessage(err));
      setLoadError(true);
    } finally {
      setChecking(false);
    }
  }, [runId, hypothesisId, outcomeId]);

  useEffect(() => {
    let current = true;
    setChecking(true);
    setAction(null);
    setError(null);
    setLoadError(false);
    setReplayed(false);
    void loadSavedAction(runId, hypothesisId, outcomeId)
      .then(savedAction => {
        if (current) setAction(savedAction);
      })
      .catch(err => {
        if (!current) return;
        setError(errorMessage(err));
        setLoadError(true);
      })
      .finally(() => {
        if (current) setChecking(false);
      });
    return () => {
      current = false;
    };
  }, [runId, hypothesisId, outcomeId]);

  const requestOrReplay = useCallback(async () => {
    setBusy(true);
    setError(null);
    setLoadError(false);
    try {
      const requestedAction = await requestHypothesisOutcomeRefinement(
        runId,
        hypothesisId,
        outcomeId,
      );
      setAction(requestedAction);
      setReplayed(requestedAction.replayed);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, [runId, hypothesisId, outcomeId]);

  return {
    action,
    checking,
    busy,
    error,
    loadError,
    replayed,
    refreshSavedAction,
    requestOrReplay,
  };
}

async function loadSavedAction(
  runId: string,
  hypothesisId: string,
  outcomeId: string,
): Promise<OutcomeRefinementAction | null> {
  try {
    return await getHypothesisOutcomeRefinement(runId, hypothesisId, outcomeId);
  } catch (err) {
    if (err instanceof HttpError && err.status === 404) return null;
    throw err;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

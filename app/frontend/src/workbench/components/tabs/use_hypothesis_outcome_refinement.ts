import {useCallback, useEffect, useState} from 'react';
import {
  getHypothesisOutcomeRefinement,
  HttpError,
  requestHypothesisOutcomeRefinement,
  type OutcomeRefinementAction,
} from '@/api/runs';

export function useHypothesisOutcomeRefinement(
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

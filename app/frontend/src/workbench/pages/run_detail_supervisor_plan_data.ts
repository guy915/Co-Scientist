import {useCallback, useEffect, useRef, useState} from 'react';
import {getSupervisorPlan, type SupervisorPlanResponse} from '@/api/runs';

export interface SupervisorPlanLoadState {
  response: SupervisorPlanResponse | null;
  loading: boolean;
  error: string | null;
}

type RunTaggedPlanState = SupervisorPlanLoadState & {
  runId: string | undefined;
};

function isCurrentRequest(
  shownId: string | undefined,
  currentRequest: number,
  id: string,
  request: number,
): boolean {
  return shownId === id && currentRequest === request;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Fetches the optional allocation ledger outside the run-detail load path. */
export function useRunSupervisorPlan(id: string | undefined) {
  const [state, setState] = useState<RunTaggedPlanState>({
    runId: id,
    response: null,
    loading: Boolean(id),
    error: null,
  });
  const shownId = useRef(id);
  const requestId = useRef(0);

  const refresh = useCallback(async () => {
    if (!id) return;
    const request = ++requestId.current;
    setState(current => ({...current, loading: true, error: null}));
    try {
      const response = await getSupervisorPlan(id);
      if (!isCurrentRequest(shownId.current, requestId.current, id, request))
        return;
      setState({runId: id, response, loading: false, error: null});
    } catch (error) {
      if (!isCurrentRequest(shownId.current, requestId.current, id, request))
        return;
      setState(current => ({
        ...current,
        loading: false,
        error: errorMessage(error),
      }));
    }
  }, [id]);

  useEffect(() => {
    shownId.current = id;
    requestId.current += 1;
    setState({runId: id, response: null, loading: Boolean(id), error: null});
    void refresh();
  }, [id, refresh]);

  const currentState: SupervisorPlanLoadState =
    state.runId === id
      ? state
      : {response: null, loading: Boolean(id), error: null};
  return {state: currentState, refresh};
}

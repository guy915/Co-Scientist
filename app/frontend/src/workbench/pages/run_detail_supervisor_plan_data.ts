import {useCallback, useEffect, useRef, useState} from 'react';
import {getSupervisorPlan, type SupervisorPlanResponse} from '@/api/runs';

export interface SupervisorPlanLoadState {
  response: SupervisorPlanResponse | null;
  loading: boolean;
  error: string | null;
}

/** Fetches the optional allocation ledger outside the run-detail load path. */
export function useRunSupervisorPlan(id: string | undefined) {
  const [state, setState] = useState<SupervisorPlanLoadState>({
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
      if (shownId.current !== id || requestId.current !== request) return;
      setState({response, loading: false, error: null});
    } catch (error) {
      if (shownId.current !== id || requestId.current !== request) return;
      setState(current => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }, [id]);

  useEffect(() => {
    shownId.current = id;
    requestId.current += 1;
    setState({response: null, loading: Boolean(id), error: null});
    void refresh();
  }, [id, refresh]);

  return {state, refresh};
}

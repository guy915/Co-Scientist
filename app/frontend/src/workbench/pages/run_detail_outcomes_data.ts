import {useCallback, useRef, useState} from 'react';
import {getHypothesisOutcomes, type HypothesisOutcome} from '@/api/runs';

async function fetchOutcomes(id: string) {
  try {
    return {data: await getHypothesisOutcomes(id), error: null};
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

/** Keeps the append-only outcome collection isolated from report fetch errors. */
export function useRunOutcomeCollection() {
  const [outcomes, setOutcomes] = useState<HypothesisOutcome[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const shownId = useRef<string | undefined>(undefined);
  const requestGeneration = useRef(0);

  const reset = useCallback((id: string | undefined) => {
    shownId.current = id;
    requestGeneration.current += 1;
    setOutcomes([]);
    setLoading(true);
    setError(null);
  }, []);

  const refresh = useCallback(async (id: string | undefined) => {
    if (!id) return;
    const generation = ++requestGeneration.current;
    setLoading(true);
    const result = await fetchOutcomes(id);
    if (shownId.current !== id || requestGeneration.current !== generation) {
      return;
    }
    if (result.data) setOutcomes(result.data);
    setError(result.error);
    setLoading(false);
  }, []);

  return {outcomes, loading, error, reset, refresh};
}

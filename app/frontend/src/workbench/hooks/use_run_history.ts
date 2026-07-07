import {useCallback, useEffect, useMemo, useState} from 'react';
import {loadRunHistory, type Run} from '@/api/runs';

/**
 * Loads the run history (owned + demo runs, de-duplicated and sorted) and the
 * top-Elo score for each completed run.
 *
 * The top-Elo score rides the run-list payload (`top_elo`), computed server-side
 * in one aggregate query, so no per-run hypothesis fetch is needed.
 *
 * @returns The run history, a map of run id to top Elo score, and a callback
 *   that reloads the history.
 */
export function useRunHistory(): {
  history: Run[];
  homeScores: Record<string, number | null>;
  reloadHistory: () => Promise<void>;
} {
  const [history, setHistory] = useState<Run[]>([]);

  const reloadHistory = useCallback(async () => {
    setHistory(await loadRunHistory());
  }, []);

  useEffect(() => {
    void reloadHistory();
  }, [reloadHistory]);

  const homeScores = useMemo(() => {
    const scores: Record<string, number | null> = {};
    for (const run of history) {
      if (run.status === 'completed') scores[run.id] = run.top_elo ?? null;
    }
    return scores;
  }, [history]);

  return {history, homeScores, reloadHistory};
}

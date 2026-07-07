import {useCallback, useEffect, useState} from 'react';
import {getHypotheses, loadRunHistory, type Run} from '@/api/runs';
import {topEloFromHypotheses} from '../pages/home_recents';

/**
 * Loads the run history (owned + demo runs, de-duplicated and sorted) and the
 * top-Elo score for each recently completed run.
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
  const [homeScores, setHomeScores] = useState<Record<string, number | null>>(
    {},
  );

  const reloadHistory = useCallback(async () => {
    setHistory(await loadRunHistory());
  }, []);

  useEffect(() => {
    void reloadHistory();
  }, [reloadHistory]);

  useEffect(() => {
    const completedRuns = history
      .filter(run => run.status === 'completed')
      .slice(0, 10);
    if (!completedRuns.length) {
      setHomeScores({});
      return;
    }

    let cancelled = false;
    void Promise.all(
      completedRuns.map(async run => {
        try {
          const hypotheses = await getHypotheses(run.id);
          return [run.id, topEloFromHypotheses(hypotheses)] as const;
        } catch {
          return [run.id, null] as const;
        }
      }),
    ).then(entries => {
      if (cancelled) return;
      setHomeScores(Object.fromEntries(entries));
    });

    return () => {
      cancelled = true;
    };
  }, [history]);

  return {history, homeScores, reloadHistory};
}

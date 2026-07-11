import {useMemo} from 'react';
import {type Run} from '@/api/runs';
import {useRunHistoryContext} from './run_history_context';

/**
 * Home-recents view of the shared run history: the run list (from
 * {@link useRunHistoryContext}, shared with the shell sidebar so it is fetched
 * once) plus the top-Elo score for each completed run.
 *
 * The top-Elo score rides the run-list payload (`top_elo`), computed
 * server-side in one aggregate query, so no per-run hypothesis fetch is
 * needed.
 *
 * @returns The run history, a map of run id to top Elo score, and a callback
 *   that reloads the shared history.
 */
export function useRunHistory(): {
  history: Run[];
  homeScores: Record<string, number | null>;
  reloadHistory: () => Promise<void>;
} {
  const {history, reload} = useRunHistoryContext();

  // Derived run-id -> top-Elo map for completed runs only; memoized on
  // `history` so the object identity is stable between reloads and doesn't
  // invalidate downstream memo/effect deps every render.
  const homeScores = useMemo(() => {
    const scores: Record<string, number | null> = {};
    for (const run of history) {
      if (run.status === 'completed') scores[run.id] = run.top_elo ?? null;
    }
    return scores;
  }, [history]);

  return {history, homeScores, reloadHistory: reload};
}

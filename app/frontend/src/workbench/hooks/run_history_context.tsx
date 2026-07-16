import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import {useLocation} from 'react-router-dom';
import {isActiveStatus, loadRunHistory, type Run} from '@/api/runs';

interface RunHistoryContextValue {
  history: Run[];
  reload: () => Promise<void>;
}

const RunHistoryContext = createContext<RunHistoryContextValue | null>(null);

// How often to re-read the history while a run is still executing. A run's
// phases last minutes, so this only has to be fast enough that the recents
// step flow does not look stuck.
const ACTIVE_RUN_REFRESH_MS = 10_000;

/**
 * Single source of truth for the run-history list, shared by the shell sidebar
 * (see useChatHistory) and the home recents (see useRunHistory) so the list is
 * fetched once and both surfaces stay in sync instead of holding two copies.
 *
 * Reloads on mount, on every navigation (so a run finishing elsewhere is
 * reflected without a full reload), and on the `cosci-runs-changed` signal a
 * newly created/started run dispatches -- the union of both former hooks'
 * triggers. While a run is still executing it also refreshes on a timer, since
 * none of those triggers fire as a run advances and the home recents show its
 * live progress.
 */
export function RunHistoryProvider({children}: {children: ReactNode}) {
  const {pathname} = useLocation();
  const [history, setHistory] = useState<Run[]>([]);

  // Stable identity (no deps) so it can be both an effect dependency and an
  // event-listener reference below, and safely handed to consumers as their
  // reload callback.
  const reload = useCallback(async () => {
    setHistory(await loadRunHistory());
  }, []);

  useEffect(() => {
    void reload();
    window.addEventListener('cosci-runs-changed', reload);
    return () => {
      window.removeEventListener('cosci-runs-changed', reload);
    };
  }, [reload, pathname]);

  // Depend on the flag rather than `history` itself so the timer is not torn
  // down and rebuilt by the state update each refresh performs.
  const hasActiveRun = history.some(run => isActiveStatus(run.status));
  useEffect(() => {
    if (!hasActiveRun) return;
    const timer = window.setInterval(
      () => void reload(),
      ACTIVE_RUN_REFRESH_MS,
    );
    return () => {
      window.clearInterval(timer);
    };
  }, [hasActiveRun, reload]);

  return (
    <RunHistoryContext.Provider value={{history, reload}}>
      {children}
    </RunHistoryContext.Provider>
  );
}

/**
 * Reads the shared run-history context. Throws when used outside
 * {@link RunHistoryProvider}, which wraps the whole workbench shell.
 */
export function useRunHistoryContext(): RunHistoryContextValue {
  const ctx = useContext(RunHistoryContext);
  if (!ctx) {
    throw new Error(
      'useRunHistoryContext must be used within a RunHistoryProvider',
    );
  }
  return ctx;
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import {useLocation} from 'react-router-dom';
import {loadRunHistory, type Run} from '@/api/runs';

interface RunHistoryContextValue {
  history: Run[];
  reload: () => Promise<void>;
}

const RunHistoryContext = createContext<RunHistoryContextValue | null>(null);

/**
 * Single source of truth for the run-history list, shared by the shell sidebar
 * (see useChatHistory) and the home recents (see useRunHistory) so the list is
 * fetched once and both surfaces stay in sync instead of holding two copies.
 *
 * Reloads on mount, on every navigation (so a run finishing elsewhere is
 * reflected without a full reload), and on the `cosci-runs-changed` signal a
 * newly created/started run dispatches -- the union of both former hooks'
 * triggers.
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

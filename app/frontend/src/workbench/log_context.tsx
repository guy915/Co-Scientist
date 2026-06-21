import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {getRunEventsLog, listRuns, type RunEvent} from '@/api/runs';

/** A single log entry enriched with the run it came from. */
export interface LogEntry extends RunEvent {
  run_id: string;
  /** Short label shown in the panel (first 40 chars of the goal). */
  run_label: string;
}

interface LogContextValue {
  /** Flat, time-sorted list of all log entries across every visited run. */
  entries: LogEntry[];
  /** Whether a background fetch is in progress. */
  loading: boolean;
  /** Manually refresh all known runs. */
  refresh: () => Promise<void>;
  /** Clear the current console view (backend run history is not deleted). */
  clear: () => void;
}

const LogContext = createContext<LogContextValue>({
  entries: [],
  loading: false,
  refresh: async () => {},
  clear: () => {},
});

/** Consumes the global log context. */
export function useLogs(): LogContextValue {
  return useContext(LogContext);
}

/**
 * App-level provider that maintains a flat, time-sorted event log across all
 * of the user's runs. It fetches the complete event history for every run the
 * current client owns on mount and whenever `refresh` is called. New runs that
 * appear are picked up automatically via a 30-second polling interval.
 */
export function LogProvider({children}: {children: ReactNode}) {
  // Map of run_id → RunEvent[] for deduplication
  const eventsByRun = useRef<Map<string, LogEntry[]>>(new Map());
  // Map of run_id → short label
  const labelsRef = useRef<Map<string, string>>(new Map());
  // Event keys (`run_id:seq`) the user has cleared. Filtered out of every
  // rebuild so the 30s poll / refresh cannot resurrect them; genuinely new
  // events get new keys and still appear.
  const dismissed = useRef<Set<string>>(new Set());
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const rebuild = useCallback(() => {
    const all: LogEntry[] = [];
    for (const evs of eventsByRun.current.values()) {
      all.push(...evs);
    }
    const visible = all.filter(
      ev => !dismissed.current.has(`${ev.run_id}:${ev.seq}`),
    );
    visible.sort((a, b) => a.created_at - b.created_at);
    setEntries(visible);
  }, []);

  const loadRun = useCallback(
    async (runId: string, label: string) => {
      try {
        const evs = await getRunEventsLog(runId);
        labelsRef.current.set(runId, label);
        eventsByRun.current.set(
          runId,
          evs.map(ev => ({...ev, run_id: runId, run_label: label})),
        );
        rebuild();
      } catch {
        /* ignore */
      }
    },
    [rebuild],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const runs = await listRuns(1000);
      await Promise.all(
        runs.map(r =>
          loadRun(
            r.id,
            r.research_goal.slice(0, 40) || `Run ${r.id.slice(0, 8)}`,
          ),
        ),
      );
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [loadRun]);

  // Initial load
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll every 30 s so live runs surface new events without requiring
  // the user to navigate anywhere.
  useEffect(() => {
    const id = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  // Clear the console view. Marks every currently-known event as dismissed so a
  // later refresh or the 30s poll cannot bring it back; new events still show.
  // Backend run history is not deleted.
  const clear = useCallback(() => {
    for (const evs of eventsByRun.current.values()) {
      for (const ev of evs) {
        dismissed.current.add(`${ev.run_id}:${ev.seq}`);
      }
    }
    setEntries([]);
  }, []);

  return (
    <LogContext.Provider value={{entries, loading, refresh, clear}}>
      {children}
    </LogContext.Provider>
  );
}

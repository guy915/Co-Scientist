import {useEffect, useState} from 'react';
import {getSystemStatus, type SystemStatus} from '@/api/system';

/** How often the workbench re-checks backend availability. */
const REFRESH_INTERVAL_MS = 60_000;

/** The workbench's view of backend system status. */
export interface SystemStatusState {
  /** The last successful /status payload, or null before the first one. */
  status: SystemStatus | null;
  /** True when the most recent fetch failed (API unreachable). */
  unreachable: boolean;
}

/**
 * Polls the backend `/status` endpoint for the workbench health indicator.
 *
 * Fetches once on mount and then on a slow interval; the backend caches
 * its own availability probes, so this stays cheap. A failed fetch flags
 * the API as unreachable but keeps the last known payload for display.
 *
 * Consumers should read {@link useSystemStatus} from
 * `hooks/system_status_context` instead, which shares one poll across the
 * whole shell; this is the polling engine behind it.
 *
 * @param options.enabled Set false to hold the poll (used by the context's
 *   fallback, which must call this hook unconditionally but only wants it to
 *   run when no provider is mounted).
 * @returns The latest system status and reachability flag.
 */
export function usePolledSystemStatus(
  {enabled}: {enabled: boolean} = {enabled: true},
): SystemStatusState {
  const [state, setState] = useState<SystemStatusState>({
    status: null,
    unreachable: false,
  });

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;

    async function refresh() {
      try {
        const status = await getSystemStatus();
        if (!disposed) setState({status, unreachable: false});
      } catch {
        if (!disposed) {
          setState(current => ({...current, unreachable: true}));
        }
      }
    }

    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [enabled]);

  return state;
}

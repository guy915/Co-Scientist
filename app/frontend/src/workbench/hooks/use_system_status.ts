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
 * @returns The latest system status and reachability flag.
 */
export function useSystemStatus(): SystemStatusState {
  const [state, setState] = useState<SystemStatusState>({
    status: null,
    unreachable: false,
  });

  useEffect(() => {
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
  }, []);

  return state;
}

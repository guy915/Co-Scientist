import {createContext, useContext, type ReactNode} from 'react';
import {
  usePolledSystemStatus,
  type SystemStatusState,
} from './use_system_status';

const SystemStatusContext = createContext<SystemStatusState | null>(null);

/**
 * Single source of truth for the `/status` payload.
 *
 * Mounted for the shell's whole lifetime so the answer is already in hand
 * wherever it is read. The connectors menu is why this is a context and not a
 * hook per consumer: the menu mounts only while it is open, so its own poll
 * started from `null` on every open and painted the PubMed-only fallback
 * until a fresh round trip landed -- which reads as the connector list
 * failing to load.
 */
export function SystemStatusProvider({children}: {children: ReactNode}) {
  const state = usePolledSystemStatus();
  return (
    <SystemStatusContext.Provider value={state}>
      {children}
    </SystemStatusContext.Provider>
  );
}

/**
 * Reads the shared system status. Falls back to polling locally when no
 * provider is mounted, so a component rendered outside the shell (a test
 * harness, a standalone page) still works.
 */
export function useSystemStatus(): SystemStatusState {
  const shared = useContext(SystemStatusContext);
  const local = usePolledSystemStatus({enabled: shared === null});
  return shared ?? local;
}

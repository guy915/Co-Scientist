import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import {getSystemStatus, type SystemStatus} from '@/api/system';

interface SystemStatusState {
  status: SystemStatus | null;
  unreachable: boolean;
}

const SystemStatusContext = createContext<SystemStatusState | null>(null);

function usePolledSystemStatus(enabled = true): SystemStatusState {
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
        if (!disposed) setState(current => ({...current, unreachable: true}));
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [enabled]);
  return state;
}

// Keep one poll alive across shell controls, including the connectors menu.
export function SystemStatusProvider({children}: {children: ReactNode}) {
  const state = usePolledSystemStatus();
  return (
    <SystemStatusContext.Provider value={state}>
      {children}
    </SystemStatusContext.Provider>
  );
}

export function useSystemStatus(): SystemStatusState {
  const shared = useContext(SystemStatusContext);
  // Isolated consumers still poll; shell consumers share the provider's read.
  const local = usePolledSystemStatus(shared === null);
  return shared ?? local;
}

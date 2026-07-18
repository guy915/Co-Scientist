import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

// Self-declared audience. Persisted in localStorage; honor system, no server
// verification. `null` means the user has not chosen yet (show the dialog).
export type Audience = 'general' | 'google' | 'sbi_ucd';

const STORAGE_KEY = 'cosci-audience';
const VALID: readonly Audience[] = ['general', 'google', 'sbi_ucd'];

interface AudienceContextValue {
  audience: Audience | null;
  setAudience: (a: Audience) => void;
}

const AudienceContext = createContext<AudienceContextValue | null>(null);

// Reads the stored audience; unknown/absent values (and non-browser
// environments) read as null so the first-visit dialog shows.
function readStoredAudience(): Audience | null {
  if (typeof window === 'undefined') return null;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return VALID.includes(stored as Audience) ? (stored as Audience) : null;
}

/**
 * Provides the self-declared audience and persists changes to localStorage.
 *
 * @param props.children The subtree that consumes the audience context.
 */
export function AudienceProvider({children}: {children: ReactNode}) {
  const [audience, setAudienceState] = useState<Audience | null>(
    readStoredAudience,
  );

  useEffect(() => {
    if (audience) window.localStorage.setItem(STORAGE_KEY, audience);
  }, [audience]);

  const setAudience = useCallback((a: Audience) => setAudienceState(a), []);

  const value = useMemo(
    () => ({audience, setAudience}),
    [audience, setAudience],
  );

  return (
    <AudienceContext.Provider value={value}>
      {children}
    </AudienceContext.Provider>
  );
}

/**
 * Returns the current audience and its setter from {@link AudienceProvider}.
 *
 * @returns The active audience (or null if unchosen) and its setter.
 */
export function useAudience(): AudienceContextValue {
  const ctx = useContext(AudienceContext);
  if (!ctx) throw new Error('useAudience used outside AudienceProvider');
  return ctx;
}

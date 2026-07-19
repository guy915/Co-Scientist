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

// What an unchosen audience resolves to. The general audience is the plain
// workspace, so this is also the safe fallback for anyone who dismisses the
// chooser without answering.
export const DEFAULT_AUDIENCE: Audience = 'general';

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
 * @param props.initialAudience Starts the provider already resolved instead
 *   of reading storage. Consumers that act on the *first* rendered value —
 *   AudienceGate decides whether to open the chooser — cannot be exercised by
 *   setting the audience afterwards, since that lands a render too late.
 */
export function AudienceProvider({
  children,
  initialAudience,
}: {
  children: ReactNode;
  initialAudience?: Audience;
}) {
  const [audience, setAudienceState] = useState<Audience | null>(
    () => initialAudience ?? readStoredAudience(),
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

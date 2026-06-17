import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
} from 'react';
import {applyMd3Theme} from '../lib/theme';

type Mode = 'light' | 'dark';

const STORAGE_KEY = 'coscientist-theme';

interface ThemeContextValue {
  mode: Mode;
  setMode: (m: Mode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function getSystemMode(): Mode {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

/**
 * Provides light/dark theme state and applies the MD3 theme to the document.
 *
 * @param props The subtree that consumes the theme context.
 */
export function ThemeProvider({children}: {children: ReactNode}) {
  // User override stored in localStorage; null = follow system.
  const [userOverride, setUserOverride] = useState<Mode | null>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored === 'light' || stored === 'dark' ? stored : null;
    } catch {
      return null;
    }
  });

  const [systemMode, setSystemMode] = useState<Mode>(getSystemMode);

  const mode: Mode = userOverride ?? systemMode;

  useLayoutEffect(() => {
    applyMd3Theme(mode === 'dark');
    document.documentElement.dataset.theme = mode;
    document.documentElement.classList.toggle('dark', mode === 'dark');
  }, [mode]);

  // Track live system changes — only applies when user hasn't overridden.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const listener = (e: MediaQueryListEvent) =>
      setSystemMode(e.matches ? 'dark' : 'light');
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, []);

  const setMode = useCallback((m: Mode) => {
    setUserOverride(m);
    try {
      localStorage.setItem(STORAGE_KEY, m);
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback(() => {
    const next: Mode = mode === 'dark' ? 'light' : 'dark';
    setUserOverride(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, [mode]);

  return (
    <ThemeContext.Provider value={{mode, setMode, toggle}}>
      {children}
    </ThemeContext.Provider>
  );
}

/**
 * Returns the current theme mode and its setters from {@link ThemeProvider}.
 *
 * @returns The active mode plus its set and toggle actions.
 */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme used outside ThemeProvider');
  return ctx;
}

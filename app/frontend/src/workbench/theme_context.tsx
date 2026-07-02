import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from 'react';
import {applyMd3Theme} from '../lib/theme';

type Mode = 'system' | 'light' | 'dark';
type ResolvedMode = 'light' | 'dark';

interface ThemeContextValue {
  mode: Mode;
  resolvedMode: ResolvedMode;
  setMode: (m: Mode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Provides the dark reference theme and applies the MD3 theme to the document.
 *
 * @param props The subtree that consumes the theme context.
 */
export function ThemeProvider({children}: {children: ReactNode}) {
  const [mode, setModeState] = useState<Mode>(() => {
    if (typeof window === 'undefined') return 'system';
    const stored = window.localStorage.getItem('cosci-theme');
    return stored === 'light' || stored === 'dark' || stored === 'system'
      ? stored
      : 'system';
  });
  const [systemMode, setSystemMode] = useState<ResolvedMode>(() => {
    if (typeof window === 'undefined') return 'dark';
    if (!window.matchMedia) return 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  });
  const resolvedMode = mode === 'system' ? systemMode : mode;

  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    function onChange() {
      setSystemMode(media.matches ? 'dark' : 'light');
    }
    if (media.addEventListener) {
      media.addEventListener('change', onChange);
      return () => media.removeEventListener('change', onChange);
    }
    media.addListener(onChange);
    return () => media.removeListener(onChange);
  }, []);

  useLayoutEffect(() => {
    const root = document.documentElement;
    // Freeze transitions across the swap so light/dark toggling doesn't animate
    // every color on the page (re-enabled after the new styles are applied).
    root.classList.add('theme-switching');
    applyMd3Theme(resolvedMode === 'dark');
    root.dataset.theme = resolvedMode;
    root.dataset.themePreference = mode;
    root.classList.toggle('dark', resolvedMode === 'dark');
    window.localStorage.setItem('cosci-theme', mode);
    const id = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        root.classList.remove('theme-switching');
      });
    });
    return () => window.cancelAnimationFrame(id);
  }, [mode, resolvedMode]);

  const setMode = useCallback((m: Mode) => {
    setModeState(m);
  }, []);

  const toggle = useCallback(() => {
    setModeState(current => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  const value = useMemo(
    () => ({mode, resolvedMode, setMode, toggle}),
    [mode, resolvedMode, setMode, toggle],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
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

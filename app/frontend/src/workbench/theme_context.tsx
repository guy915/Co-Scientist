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
import {flushSync} from 'react-dom';
import {MD3_SCHEMES} from './md3_scheme';

export type Mode = 'system' | 'light' | 'dark';
type ResolvedMode = 'light' | 'dark';

interface ThemeContextValue {
  mode: Mode;
  resolvedMode: ResolvedMode;
  setMode: (m: Mode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredMode(): Mode {
  if (typeof window === 'undefined') return 'system';
  const stored = window.localStorage.getItem('cosci-theme');
  return stored === 'light' || stored === 'dark' || stored === 'system'
    ? stored
    : 'system';
}

// Without matchMedia in jsdom/prerender, use the app’s dark reference theme.
function readSystemMode(): ResolvedMode {
  if (typeof window === 'undefined') return 'dark';
  if (!window.matchMedia) return 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

// Older Safari lacks MediaQueryList add/removeEventListener; retain its
// listener fallback.
function useSystemColorScheme(): ResolvedMode {
  const [systemMode, setSystemMode] = useState<ResolvedMode>(readSystemMode);

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

  return systemMode;
}

// Apply before paint to avoid a stale-theme flash; persist preference, not
// resolved brightness, so system mode survives reload.
function useApplyTheme(mode: Mode, resolvedMode: ResolvedMode): void {
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.classList.add('theme-switching');
    applyMd3Theme(resolvedMode === 'dark');
    root.dataset.theme = resolvedMode;
    root.dataset.themePreference = mode;
    root.classList.toggle('dark', resolvedMode === 'dark');
    window.localStorage.setItem('cosci-theme', mode);
    // The first animation frame commits styles; the second lifts transition
    // suppression after they are visible.
    const id = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        root.classList.remove('theme-switching');
      });
    });
    return () => window.cancelAnimationFrame(id);
  }, [mode, resolvedMode]);
}

// A chosen theme cross-fades the whole page (shared/ui/motion.css) instead of
// repainting at once. The update commits synchronously inside the transition so
// the new snapshot already carries the new palette.
function crossFade(update: () => void): void {
  if (typeof document.startViewTransition !== 'function') {
    update();
    return;
  }
  document.startViewTransition(() => flushSync(update));
}

export function ThemeProvider({children}: {children: ReactNode}) {
  const [mode, setModeState] = useState<Mode>(readStoredMode);
  const systemMode = useSystemColorScheme();
  const resolvedMode = mode === 'system' ? systemMode : mode;

  useApplyTheme(mode, resolvedMode);

  const setMode = useCallback((m: Mode) => {
    crossFade(() => setModeState(m));
  }, []);

  const toggle = useCallback(() => {
    crossFade(() =>
      setModeState(current => (current === 'dark' ? 'light' : 'dark')),
    );
  }, []);

  const value = useMemo(
    () => ({mode, resolvedMode, setMode, toggle}),
    [mode, resolvedMode, setMode, toggle],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme used outside ThemeProvider');
  return ctx;
}

export function applyMd3Theme(dark: boolean): void {
  const style = document.documentElement.style;
  for (const [token, color] of Object.entries(
    MD3_SCHEMES[dark ? 'dark' : 'light'],
  )) {
    style.setProperty(token, color);
  }
}

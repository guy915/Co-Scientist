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
import {
  applyTheme,
  argbFromHex,
  themeFromSourceColor,
} from '@material/material-color-utilities';

// The user's stored preference: 'system' defers to the OS color scheme.
export type Mode = 'system' | 'light' | 'dark';
// What is actually applied to the document after resolving 'system'.
type ResolvedMode = 'light' | 'dark';

interface ThemeContextValue {
  mode: Mode; // stored preference (may be 'system')
  resolvedMode: ResolvedMode; // what the document currently shows
  setMode: (m: Mode) => void;
  toggle: () => void; // flips light/dark directly, leaving 'system' behind
}

// Theme state lives in plain React context (no external state library);
// consumers read it via the useTheme hook below.
const ThemeContext = createContext<ThemeContextValue | null>(null);

// Reads the stored theme preference (key 'cosci-theme'); unknown/absent
// values (and non-browser environments) fall back to 'system'.
function readStoredMode(): Mode {
  if (typeof window === 'undefined') return 'system';
  const stored = window.localStorage.getItem('cosci-theme');
  return stored === 'light' || stored === 'dark' || stored === 'system'
    ? stored
    : 'system';
}

// Reads the OS-level color scheme; defaults to dark when matchMedia is
// missing (jsdom/prerender), matching the app's dark reference theme.
function readSystemMode(): ResolvedMode {
  if (typeof window === 'undefined') return 'dark';
  if (!window.matchMedia) return 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

// Tracks the OS-level color scheme for the caller's lifetime, so 'system'
// mode resolves against it live. The addListener/removeListener branch
// covers older Safari, where MediaQueryList lacks add/removeEventListener.
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

// Applies the resolved theme to the document. useLayoutEffect (not
// useEffect) so the swap happens before paint and a toggle never flashes the
// old theme for a frame. applyMd3Theme() regenerates the runtime MD3 token
// set (--md-sys-color-*) from the seed color for the chosen brightness; the
// data-theme/data-themePreference attributes and the `dark` class are what
// CSS selectors and Tailwind key off. The preference (not the resolved mode)
// is what gets persisted, so 'system' stays 'system' across reloads.
function useApplyTheme(mode: Mode, resolvedMode: ResolvedMode): void {
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
    // Double-rAF: the first frame commits the new styles, the second lifts
    // the transition freeze only after they are visible.
    const id = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        root.classList.remove('theme-switching');
      });
    });
    return () => window.cancelAnimationFrame(id);
  }, [mode, resolvedMode]);
}

/**
 * Provides the dark reference theme and applies the MD3 theme to the document.
 *
 * @param props The subtree that consumes the theme context.
 */
export function ThemeProvider({children}: {children: ReactNode}) {
  // Preference is initialized from localStorage so a reload keeps the user's
  // choice; lazy initializer so storage is read once, not every render.
  const [mode, setModeState] = useState<Mode>(readStoredMode);
  // The OS-level color scheme, tracked separately so 'system' mode can
  // resolve against it live.
  const systemMode = useSystemColorScheme();
  const resolvedMode = mode === 'system' ? systemMode : mode;

  useApplyTheme(mode, resolvedMode);

  const setMode = useCallback((m: Mode) => {
    setModeState(m);
  }, []);

  // Toggle resolves to an explicit light/dark choice (from whatever is
  // currently stored), intentionally leaving 'system' mode.
  const toggle = useCallback(() => {
    setModeState(current => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  // Memoized so consumers of the context don't re-render unless the mode
  // actually changes (the callbacks above are stable).
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

// The single MD3 source color for the whole app (a teal). Every
// --md-sys-color-* token is derived from it at runtime, so palette changes
// happen here, never by hardcoding token values (see frontend/DESIGN.md).
const SEED = '#1A6B6B';

// themeFromSourceColor expands the seed into full MD3 tonal palettes with
// light and dark schemes. It depends only on the (constant) seed, so derive it
// once at module load rather than on every applyMd3Theme call.
const THEME = themeFromSourceColor(argbFromHex(SEED));

/**
 * Generates the Material Design 3 theme from the seed color and applies its
 * CSS custom properties to the document root.
 *
 * @param dark Whether to apply the dark color scheme.
 */
export function applyMd3Theme(dark: boolean): void {
  // applyTheme writes the chosen scheme's --md-sys-color-* custom properties
  // onto <html>, where the --color-th-* bridge variables in src/index.css pick
  // them up.
  applyTheme(THEME, {
    target: document.documentElement,
    dark,
    // Emit plain --md-sys-color-* names only, not -light/-dark suffixed
    // variants; light/dark is chosen by re-running this with `dark` toggled.
    brightnessSuffix: false,
  });
}

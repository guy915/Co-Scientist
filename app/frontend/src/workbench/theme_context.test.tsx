import {act, renderHook} from '@testing-library/react';
import type {ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {ThemeProvider, useTheme} from './theme_context';

const STORAGE_KEY = 'cosci-theme';

interface FakeMediaQueryList {
  matches: boolean;
  addEventListener?: ReturnType<typeof vi.fn>;
  removeEventListener?: ReturnType<typeof vi.fn>;
  addListener?: ReturnType<typeof vi.fn>;
  removeListener?: ReturnType<typeof vi.fn>;
  fireChange(matches: boolean): void;
}

// Installs window.matchMedia so it resolves '(prefers-color-scheme: dark)' to
// a controllable fake MediaQueryList. `style: 'legacy'` omits
// addEventListener/removeEventListener so useSystemColorScheme falls back to
// the older addListener/removeListener pair (pre-Safari-14 API).
function installFakeMatchMedia(
  initialDarkMatches: boolean,
  style: 'modern' | 'legacy' = 'modern',
) {
  const listeners = new Set<() => void>();
  const mql: FakeMediaQueryList = {
    matches: initialDarkMatches,
    fireChange(matches: boolean) {
      mql.matches = matches;
      listeners.forEach(cb => cb());
    },
  };
  if (style === 'modern') {
    mql.addEventListener = vi.fn((_event: string, cb: () => void) => {
      listeners.add(cb);
    });
    mql.removeEventListener = vi.fn((_event: string, cb: () => void) => {
      listeners.delete(cb);
    });
  } else {
    mql.addListener = vi.fn((cb: () => void) => {
      listeners.add(cb);
    });
    mql.removeListener = vi.fn((cb: () => void) => {
      listeners.delete(cb);
    });
  }
  const matchMedia = vi.fn(() => mql);
  vi.stubGlobal('matchMedia', matchMedia);
  return mql;
}

function wrapper({children}: {children: ReactNode}) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

// Flushes the double-rAF used by useApplyTheme to lift the
// 'theme-switching' transition freeze after the new styles are committed.
async function flushThemeTransition() {
  await act(async () => {
    await new Promise(resolve => requestAnimationFrame(resolve));
    await new Promise(resolve => requestAnimationFrame(resolve));
  });
}

beforeEach(() => {
  localStorage.removeItem(STORAGE_KEY);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute('style');
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-theme-preference');
  document.documentElement.className = '';
  localStorage.removeItem(STORAGE_KEY);
});

describe('ThemeProvider / useTheme', () => {
  it('defaults to system mode resolving to dark when matchMedia is unavailable', async () => {
    vi.stubGlobal('matchMedia', undefined);
    const {result} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();

    expect(result.current.mode).toBe('system');
    expect(result.current.resolvedMode).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('honors a stored explicit light preference over the system scheme', async () => {
    localStorage.setItem(STORAGE_KEY, 'light');
    installFakeMatchMedia(true); // system says dark; explicit pref should win
    const {result} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();

    expect(result.current.mode).toBe('light');
    expect(result.current.resolvedMode).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('falls back to system for an unrecognized stored value', async () => {
    localStorage.setItem(STORAGE_KEY, 'sepia');
    installFakeMatchMedia(false);
    const {result} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();

    expect(result.current.mode).toBe('system');
    expect(result.current.resolvedMode).toBe('light');
  });

  it('resolves system mode live against OS scheme changes', async () => {
    const mql = installFakeMatchMedia(false);
    const {result} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();
    expect(result.current.resolvedMode).toBe('light');

    act(() => mql.fireChange(true));
    await flushThemeTransition();
    expect(result.current.resolvedMode).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');

    act(() => mql.fireChange(false));
    await flushThemeTransition();
    expect(result.current.resolvedMode).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('subscribes via the legacy addListener/removeListener API when addEventListener is absent', async () => {
    const mql = installFakeMatchMedia(false, 'legacy');
    const {result, unmount} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();
    expect(mql.addListener).toHaveBeenCalledWith(expect.any(Function));

    act(() => mql.fireChange(true));
    await flushThemeTransition();
    expect(result.current.resolvedMode).toBe('dark');

    unmount();
    expect(mql.removeListener).toHaveBeenCalledWith(expect.any(Function));
  });

  it('setMode persists an explicit choice and updates resolvedMode', async () => {
    installFakeMatchMedia(false);
    const {result} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();

    act(() => result.current.setMode('dark'));
    await flushThemeTransition();

    expect(result.current.mode).toBe('dark');
    expect(result.current.resolvedMode).toBe('dark');
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark');
    expect(document.documentElement.dataset.themePreference).toBe('dark');
  });

  it('toggle flips between light and dark', async () => {
    installFakeMatchMedia(false);
    const {result} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();
    act(() => result.current.setMode('light'));
    await flushThemeTransition();

    act(() => result.current.toggle());
    await flushThemeTransition();
    expect(result.current.mode).toBe('dark');

    act(() => result.current.toggle());
    await flushThemeTransition();
    expect(result.current.mode).toBe('light');
  });

  it('toggle from system mode resolves to dark, leaving system behind', async () => {
    installFakeMatchMedia(false); // system currently resolves to light
    const {result} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();
    expect(result.current.mode).toBe('system');

    act(() => result.current.toggle());
    await flushThemeTransition();

    expect(result.current.mode).toBe('dark');
    expect(result.current.resolvedMode).toBe('dark');
  });

  it('lifts the theme-switching transition freeze after the theme is applied', async () => {
    installFakeMatchMedia(false);
    renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();

    expect(document.documentElement.classList.contains('theme-switching')).toBe(
      false,
    );
  });

  it('unsubscribes the modern change listener on unmount', async () => {
    const mql = installFakeMatchMedia(false);
    const {unmount} = renderHook(() => useTheme(), {wrapper});
    await flushThemeTransition();
    expect(mql.addEventListener).toHaveBeenCalledWith(
      'change',
      expect.any(Function),
    );

    unmount();
    expect(mql.removeEventListener).toHaveBeenCalledWith(
      'change',
      expect.any(Function),
    );
  });
});

describe('useTheme', () => {
  beforeEach(() => {
    // React logs the thrown render error to the console; silence the
    // expected noise.
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('throws when used outside a ThemeProvider', () => {
    expect(() => renderHook(() => useTheme())).toThrow(
      'useTheme used outside ThemeProvider',
    );
  });
});

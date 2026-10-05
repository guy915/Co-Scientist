import {act, renderHook} from '@testing-library/react';
import type {ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {applyMd3Theme, ThemeProvider, useTheme} from './theme_context';

const STORAGE_KEY = 'cosci-theme';

interface FakeMediaQueryList {
  matches: boolean;
  addEventListener?: ReturnType<typeof vi.fn>;
  removeEventListener?: ReturnType<typeof vi.fn>;
  addListener?: ReturnType<typeof vi.fn>;
  removeListener?: ReturnType<typeof vi.fn>;
  fireChange(matches: boolean): void;
}

// Legacy Safari uses addListener/removeListener instead of event-listener
// methods.
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

// Theme transition suppression ends after two animation frames commit the new
// palette.
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

it('defaults to system mode, dark when matchMedia is absent', async () => {
  vi.stubGlobal('matchMedia', undefined);
  const {result} = renderHook(() => useTheme(), {wrapper});
  await flushThemeTransition();

  expect(result.current.mode).toBe('system');
  expect(result.current.resolvedMode).toBe('dark');
  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(document.documentElement.classList.contains('dark')).toBe(true);
});

it('honors a stored light preference over the system scheme', async () => {
  localStorage.setItem(STORAGE_KEY, 'light');
  installFakeMatchMedia(true);
  const {result} = renderHook(() => useTheme(), {wrapper});
  await flushThemeTransition();

  expect(result.current.mode).toBe('light');
  expect(result.current.resolvedMode).toBe('light');
  expect(document.documentElement.dataset.theme).toBe('light');
  expect(document.documentElement.classList.contains('dark')).toBe(false);
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

it('lifts the transition freeze after the theme is applied', async () => {
  installFakeMatchMedia(false);
  renderHook(() => useTheme(), {wrapper});
  await flushThemeTransition();

  expect(document.documentElement.classList.contains('theme-switching')).toBe(
    false,
  );
});

describe('useTheme', () => {
  beforeEach(() => {
    // React logs thrown render errors; silence only the expected noise.
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });
});

function cssVar(name: string): string {
  return document.documentElement.style.getPropertyValue(name);
}

describe('applyMd3Theme', () => {
  beforeEach(() => document.documentElement.removeAttribute('style'));

  it('sets MD3 color custom properties on the document root', () => {
    applyMd3Theme(false);
    expect(cssVar('--md-sys-color-primary')).not.toBe('');
    expect(cssVar('--md-sys-color-surface')).not.toBe('');
    expect(cssVar('--md-sys-color-on-surface')).not.toBe('');
  });
});

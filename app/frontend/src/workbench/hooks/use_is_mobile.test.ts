import {act, renderHook} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {
  MOBILE_MEDIA_QUERY,
  isMobileViewport,
  useIsMobile,
} from './use_is_mobile';

interface FakeMediaQueryList {
  matches: boolean;
  media: string;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
  fireChange(matches: boolean): void;
}

// Builds a window.matchMedia stand-in that tracks one MediaQueryList per
// query string and lets tests fire 'change' events on it.
function installFakeMatchMedia(initialMatches: Record<string, boolean> = {}) {
  const lists = new Map<string, FakeMediaQueryList>();
  function getOrCreate(query: string): FakeMediaQueryList {
    let mql = lists.get(query);
    if (!mql) {
      const listeners = new Set<() => void>();
      mql = {
        matches: initialMatches[query] ?? false,
        media: query,
        addEventListener: vi.fn((_event: string, cb: () => void) => {
          listeners.add(cb);
        }),
        removeEventListener: vi.fn((_event: string, cb: () => void) => {
          listeners.delete(cb);
        }),
        fireChange(matches: boolean) {
          mql!.matches = matches;
          listeners.forEach(cb => cb());
        },
      };
      lists.set(query, mql);
    }
    return mql;
  }
  const matchMedia = vi.fn((query: string) => getOrCreate(query));
  vi.stubGlobal('matchMedia', matchMedia);
  return {matchMedia, lists};
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('isMobileViewport', () => {
  it('returns false when matchMedia is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined);
    expect(isMobileViewport()).toBe(false);
  });

  it('returns true when the mobile breakpoint matches', () => {
    installFakeMatchMedia({[MOBILE_MEDIA_QUERY]: true});
    expect(isMobileViewport()).toBe(true);
  });

  it('returns false when the mobile breakpoint does not match', () => {
    installFakeMatchMedia({[MOBILE_MEDIA_QUERY]: false});
    expect(isMobileViewport()).toBe(false);
  });
});

it('initializes from the current match state', () => {
  installFakeMatchMedia({[MOBILE_MEDIA_QUERY]: true});
  const {result} = renderHook(() => useIsMobile());
  expect(result.current).toBe(true);
});

it('initializes to false when the query does not match', () => {
  installFakeMatchMedia({[MOBILE_MEDIA_QUERY]: false});
  const {result} = renderHook(() => useIsMobile());
  expect(result.current).toBe(false);
});

it('updates when the media query change event fires', () => {
  const {lists} = installFakeMatchMedia({[MOBILE_MEDIA_QUERY]: false});
  const {result} = renderHook(() => useIsMobile());
  expect(result.current).toBe(false);

  act(() => {
    lists.get(MOBILE_MEDIA_QUERY)!.fireChange(true);
  });
  expect(result.current).toBe(true);

  act(() => {
    lists.get(MOBILE_MEDIA_QUERY)!.fireChange(false);
  });
  expect(result.current).toBe(false);
});

it('subscribes to change events on mount and unsubscribes on unmount', () => {
  const {lists} = installFakeMatchMedia({[MOBILE_MEDIA_QUERY]: false});
  const {unmount} = renderHook(() => useIsMobile());
  const mql = lists.get(MOBILE_MEDIA_QUERY)!;
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

it('resubscribes when the query argument changes', () => {
  const {lists} = installFakeMatchMedia({
    '(max-width: 700px)': false,
    '(max-width: 400px)': true,
  });
  const {result, rerender} = renderHook(({query}) => useIsMobile(query), {
    initialProps: {query: '(max-width: 700px)'},
  });
  expect(result.current).toBe(false);

  rerender({query: '(max-width: 400px)'});
  expect(result.current).toBe(true);

  const wideList = lists.get('(max-width: 700px)')!;
  const narrowList = lists.get('(max-width: 400px)')!;
  expect(wideList.removeEventListener).toHaveBeenCalled();
  expect(narrowList.addEventListener).toHaveBeenCalled();
});

it('does not crash and reads false when matchMedia is unavailable', () => {
  vi.stubGlobal('matchMedia', undefined);
  const {result} = renderHook(() => useIsMobile());
  expect(result.current).toBe(false);
});

it('defaults to MOBILE_MEDIA_QUERY when no query is given', () => {
  const {matchMedia} = installFakeMatchMedia({[MOBILE_MEDIA_QUERY]: false});
  renderHook(() => useIsMobile());
  expect(matchMedia).toHaveBeenCalledWith(MOBILE_MEDIA_QUERY);
});

import {act, renderHook, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {
  MOBILE_MEDIA_QUERY,
  isMobileViewport,
  useIsMobile,
  useOverflowing,
  useRestoreFocusOnClose,
} from './dom';

describe('use is mobile', () => {
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
});

describe('use overflowing', () => {
  // jsdom has no layout engine, so drive the two measurements the hook reads.
  function stubGeometry(
    clientHeight: number,
    childTops: number[],
    childHeight: number,
  ) {
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return this.dataset.role === 'box' ? clientHeight : childHeight;
      },
    });
    HTMLElement.prototype.getBoundingClientRect = function () {
      const index = Number(this.dataset.index ?? -1);
      const top = index >= 0 ? childTops[index] : 0;
      return {top, bottom: top + childHeight} as DOMRect;
    };
  }

  function Probe({count}: {count: number}) {
    const [ref, overflowing] = useOverflowing<HTMLDivElement>();
    return (
      <div ref={ref} data-role="box">
        <span data-testid="state">{String(overflowing)}</span>
        {Array.from({length: count}, (_, index) => (
          <p key={index} data-index={index}>
            chat {index}
          </p>
        ))}
      </div>
    );
  }

  describe('useOverflowing', () => {
    it('reports no overflow when the children fit the box', () => {
      // 3 children spanning 0..90 in a 100-tall box.
      stubGeometry(100, [0, 30, 60], 30);
      render(<Probe count={3} />);
      expect(screen.getByTestId('state')).toHaveTextContent('false');
    });

    it('reports overflow when the children outrun the box', () => {
      // 5 children spanning 0..150 in a 100-tall box.
      stubGeometry(100, [0, 30, 60, 90, 120], 30);
      render(<Probe count={5} />);
      expect(screen.getByTestId('state')).toHaveTextContent('true');
    });

    it('ignores a hidden tooltip hanging past the last child', () => {
      // The span of the children is what counts. scrollHeight would include the
      // absolutely positioned tooltip below the last row and wrongly report a
      // list that fits as overflowing -- which would clip the tooltip itself.
      stubGeometry(100, [0, 30, 60], 30);
      Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
        configurable: true,
        get() {
          return 400;
        },
      });
      render(<Probe count={3} />);
      expect(screen.getByTestId('state')).toHaveTextContent('false');
    });

    it('reports no overflow for an empty list', () => {
      stubGeometry(100, [], 30);
      render(<Probe count={0} />);
      expect(screen.getByTestId('state')).toHaveTextContent('false');
    });
  });
});

describe('use restore focus on close', () => {
  function Dialog() {
    useRestoreFocusOnClose();
    return <div>dialog body</div>;
  }

  it('returns focus to the opener when it is still on the page', () => {
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();

    const view = render(<Dialog />);
    view.unmount();

    expect(document.activeElement).toBe(opener);
  });

  // The real path in this app: the rail's Settings menu is a popover that
  // unmounts as soon as the dialog it launched opens, so by the time the
  // dialog closes the captured opener is a detached node. `.focus()` on one is
  // a silent no-op, which left focus on `<body>` -- verified in a browser
  // before this fix -- restarting tabbing from the top of the page.
  it('falls back to the nearest surviving ancestor when the opener is gone', () => {
    const rail = document.createElement('div');
    const popover = document.createElement('div');
    const menuItem = document.createElement('button');
    popover.append(menuItem);
    rail.append(popover);
    document.body.append(rail);
    menuItem.focus();

    const view = render(<Dialog />);
    // The popover (and the menu item inside it) closes behind the dialog.
    popover.remove();
    view.unmount();

    expect(document.activeElement).toBe(rail);
    expect(document.activeElement).not.toBe(document.body);
  });
});

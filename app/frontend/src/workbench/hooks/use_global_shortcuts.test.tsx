import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {renderHook} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import type {ReactNode} from 'react';
import {useGlobalShortcuts} from './use_global_shortcuts';

// Capture navigations through react-router's useNavigate without exercising a
// real router; useLocation still comes from the surrounding MemoryRouter so the
// hook reads a genuine pathname.
const navigateMock = vi.fn();
vi.mock('react-router-dom', async importOriginal => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {...actual, useNavigate: () => navigateMock};
});

/** Builds a MemoryRouter wrapper seeded at the given pathname. */
function wrapperAt(pathname: string) {
  return ({children}: {children: ReactNode}) => (
    <MemoryRouter initialEntries={[pathname]}>{children}</MemoryRouter>
  );
}

/**
 * Dispatches a keydown carrying `key` on the given target (defaults
 * document).
 */
function keyDown(key: string, target: EventTarget = document): void {
  target.dispatchEvent(
    new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true}),
  );
}

describe('useGlobalShortcuts', () => {
  beforeEach(() => navigateMock.mockReset());
  afterEach(() => {
    // Remove any stray nodes appended for the text-editing-target test.
    document.body.replaceChildren();
  });

  it('navigates to / on the "g n" sequence', () => {
    renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt('/runs')});
    keyDown('g');
    keyDown('n');
    expect(navigateMock).toHaveBeenCalledExactlyOnceWith('/');
  });

  it('does not navigate for a bare key without the leading "g"', () => {
    renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt('/runs')});
    keyDown('d');
    keyDown('n');
    expect(navigateMock).not.toHaveBeenCalled();
  });

  // Each row: starting pathname, arrow pressed, expected navigation target.
  // The 'hypotheses' row exercises the alias for 'ideas' (the last tab), so
  // ArrowLeft steps back to 'overview' rather than mistaking the route for the
  // 'details' default and stepping forward.
  it.each([
    ['/runs/abc', 'ArrowRight', '/runs/abc/learning'],
    ['/runs/abc/overview', 'ArrowRight', '/runs/abc/ideas'],
    ['/runs/abc/overview', 'ArrowLeft', '/runs/abc/learning'],
    ['/runs/abc/learning', 'ArrowLeft', '/runs/abc/details'],
    ['/runs/abc/hypotheses', 'ArrowLeft', '/runs/abc/overview'],
  ])('cycles from %s on %s to %s', (path, key, target) => {
    renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt(path)});
    keyDown(key);
    expect(navigateMock).toHaveBeenCalledExactlyOnceWith(target);
  });

  // ArrowRight is a no-op past the last tab (ideas, and its 'hypotheses' alias)
  // and off any run page.
  it.each(['/runs/abc/ideas', '/runs/abc/hypotheses', '/runs'])(
    'does not navigate on ArrowRight from %s',
    path => {
      renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt(path)});
      keyDown('ArrowRight');
      expect(navigateMock).not.toHaveBeenCalled();
    },
  );

  it('ignores shortcuts while typing in an input', () => {
    renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt('/runs')});
    const input = document.createElement('input');
    document.body.appendChild(input);
    // The event bubbles to the document listener with target === the input, so
    // isTextEditingTarget() short-circuits the handler.
    keyDown('g', input);
    keyDown('d', input);
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('ignores shortcuts when a modifier key is held', () => {
    renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt('/runs')});
    document.dispatchEvent(
      new KeyboardEvent('keydown', {key: 'g', metaKey: true, bubbles: true}),
    );
    document.dispatchEvent(
      new KeyboardEvent('keydown', {key: 'd', metaKey: true, bubbles: true}),
    );
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('removes its keydown listener on unmount', () => {
    const {unmount} = renderHook(() => useGlobalShortcuts(), {
      wrapper: wrapperAt('/runs'),
    });
    unmount();
    keyDown('g');
    keyDown('d');
    expect(navigateMock).not.toHaveBeenCalled();
  });
});

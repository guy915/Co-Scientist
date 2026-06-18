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

/** Dispatches a keydown carrying `key` on the given target (defaults document). */
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

  it('navigates to /runs on the "g d" sequence', () => {
    renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt('/runs')});
    keyDown('g');
    keyDown('d');
    expect(navigateMock).toHaveBeenCalledExactlyOnceWith('/runs');
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

  it('cycles from the default chat tab on ArrowRight while on a run page', () => {
    renderHook(() => useGlobalShortcuts(), {
      wrapper: wrapperAt('/runs/abc'),
    });
    keyDown('ArrowRight');
    expect(navigateMock).toHaveBeenCalledExactlyOnceWith('/runs/abc/overview');
  });

  it('cycles from overview to ideas on ArrowRight', () => {
    renderHook(() => useGlobalShortcuts(), {
      wrapper: wrapperAt('/runs/abc/overview'),
    });
    keyDown('ArrowRight');
    expect(navigateMock).toHaveBeenCalledExactlyOnceWith('/runs/abc/ideas');
  });

  it('cycles back to chat (empty tab segment) on ArrowLeft', () => {
    renderHook(() => useGlobalShortcuts(), {
      wrapper: wrapperAt('/runs/abc/overview'),
    });
    keyDown('ArrowLeft');
    expect(navigateMock).toHaveBeenCalledExactlyOnceWith('/runs/abc/');
  });

  it('does not navigate past the last tab on ArrowRight', () => {
    renderHook(() => useGlobalShortcuts(), {
      wrapper: wrapperAt('/runs/abc/report'),
    });
    keyDown('ArrowRight');
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('ignores arrow keys when not on a run page', () => {
    renderHook(() => useGlobalShortcuts(), {wrapper: wrapperAt('/runs')});
    keyDown('ArrowRight');
    expect(navigateMock).not.toHaveBeenCalled();
  });

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

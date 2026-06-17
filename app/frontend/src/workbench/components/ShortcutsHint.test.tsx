import {describe, it, expect, beforeAll} from 'vitest';
import {render, screen} from '@testing-library/react';
import {ShortcutsHint} from './ShortcutsHint';

beforeAll(() => {
  // ShortcutsHint mounts an md-dialog, whose web component constructs an
  // IntersectionObserver in its first update; jsdom lacks it, so stub it to
  // avoid unhandled rejections.
  (window as unknown as {IntersectionObserver: unknown}).IntersectionObserver =
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
});

describe('ShortcutsHint', () => {
  it('renders the keyboard-shortcuts trigger button', () => {
    render(<ShortcutsHint />);
    expect(screen.getByLabelText('Keyboard shortcuts')).toBeInTheDocument();
  });

  it('renders the list of shortcut descriptions', () => {
    render(<ShortcutsHint />);
    // The dialog content is always present in the light DOM, slotted by
    // md-dialog regardless of its open state.
    expect(screen.getByText('Open this shortcut help')).toBeInTheDocument();
    expect(screen.getByText('Go to dashboard')).toBeInTheDocument();
    expect(screen.getByText('Start a new run')).toBeInTheDocument();
  });
});

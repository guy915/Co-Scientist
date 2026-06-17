import {describe, it, expect, beforeAll} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MdDialog} from './MdDialog';

beforeAll(() => {
  // The md-dialog web component constructs an IntersectionObserver in its
  // first update; jsdom lacks it, so stub it to avoid unhandled rejections.
  (window as unknown as {IntersectionObserver: unknown}).IntersectionObserver =
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
});

describe('MdDialog', () => {
  // Rendered closed: the headline, body, and actions are slotted into the
  // light DOM regardless of open state, so they are queryable without
  // invoking the web component's show() (which is unreliable in jsdom).
  it('renders the headline, children, and actions content', () => {
    render(
      <MdDialog
        open={false}
        onClose={() => {}}
        headline="My headline"
        actions={<button type="button">OK</button>}
      >
        <p>Dialog body</p>
      </MdDialog>,
    );
    expect(screen.getByText('My headline')).toBeInTheDocument();
    expect(screen.getByText('Dialog body')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'OK'})).toBeInTheDocument();
  });

  it('renders the body even without a headline or actions', () => {
    render(
      <MdDialog open={false} onClose={() => {}}>
        <p>Just a body</p>
      </MdDialog>,
    );
    expect(screen.getByText('Just a body')).toBeInTheDocument();
  });
});

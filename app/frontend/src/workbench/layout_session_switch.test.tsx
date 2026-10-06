import {screen} from '@testing-library/react';
import {beforeEach, expect, it, afterEach, describe} from 'vitest';
import {
  apiMock,
  chatFixture,
  installLayoutMocks,
  renderLayout,
} from './layout_test_support';
import {preferredSessionSide, writeSessionSide} from './layout_session_switch';

describe('layout session switch', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  function installStartedSession() {
    apiMock.listInterviews.mockResolvedValue([
      chatFixture('chat-7', 'Study pathway X', {run_id: 'run-1'}),
    ]);
  }

  it('switches from the results page back to the conversation', async () => {
    installStartedSession();
    renderLayout('/runs/run-1/details');

    const chat = await screen.findByRole('link', {name: 'Chat'});
    expect(chat).toHaveAttribute('href', '/chats/chat-7');
    expect(screen.getByRole('link', {name: 'Results'})).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(chat).not.toHaveAttribute('aria-current');
  });

  // Visited-link color outranks inherited color; each switch side needs its own
  // color.

  // Tailwind resolves conflicting utilities by stylesheet order, so shared
  // shape excludes display.
});

describe('layout session memory', () => {
  beforeEach(() => {
    installLayoutMocks();
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it('remembers the side per session', () => {
    writeSessionSide('run-1', 'chat');
    expect(preferredSessionSide('run-1')).toBe('chat');
  });
});

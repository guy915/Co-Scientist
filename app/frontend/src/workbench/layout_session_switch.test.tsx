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

  it('switches from the conversation to the results it produced', async () => {
    installStartedSession();
    renderLayout('/chats/chat-7');

    expect(await screen.findByRole('link', {name: 'Results'})).toHaveAttribute(
      'href',
      '/runs/run-1/details',
    );
    expect(screen.getByRole('link', {name: 'Chat'})).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('shows no switch for a conversation that never started a run', async () => {
    apiMock.listInterviews.mockResolvedValue([
      chatFixture('chat-9', 'Still deciding'),
    ]);
    renderLayout('/chats/chat-9');

    // Wait for committed history before asserting the absence of a session
    // switch.
    expect(await screen.findByText('Still deciding')).toBeInTheDocument();
    expect(screen.queryByRole('link', {name: 'Results'})).toBeNull();
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

  it('prefers a session’s own memory over the switch’s last position', () => {
    writeSessionSide('run-1', 'chat');
    writeSessionSide('run-2', 'results');
    expect(preferredSessionSide('run-1')).toBe('chat');
  });

  it('opens a rail row on the switch’s last side, not the session default', async () => {
    apiMock.listInterviews.mockResolvedValue([
      chatFixture('chat-7', 'Study pathway X', {run_id: 'run-1'}),
    ]);
    writeSessionSide('run-9', 'chat');
    renderLayout('/');

    expect(
      await screen.findByRole('link', {name: /Study pathway X/}),
    ).toHaveAttribute('href', '/chats/chat-7');
  });
});

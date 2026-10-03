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
  it('spends the accent on the sliding highlight and colours both labels itself', async () => {
    installStartedSession();
    renderLayout('/runs/run-1/details');

    const results = await screen.findByRole('link', {name: 'Results'});
    const chat = screen.getByRole('link', {name: 'Chat'});
    const track = results.closest('nav');

    const thumb = track?.querySelector('.ucs-session-switch-thumb');
    expect(thumb).not.toBeNull();
    expect(track).toHaveAttribute('data-active', 'results');
    expect(track?.className).not.toContain('bg-cosci-logs-accent-bg');
    expect(results.className).not.toContain('bg-cosci-logs-accent-bg');
    expect(chat.className).not.toContain('bg-cosci-logs-accent-bg');
    expect(track?.className).toContain('bg-cosci-recent-meta-bg');
    expect(results.className).toContain('text-cosci-logs-accent-fg');
    expect(chat.className).toContain('text-cosci-shell-icon');
  });

  // Tailwind resolves conflicting utilities by stylesheet order, so shared
  // shape excludes display.
  it("keeps the track a two-column grid, not the trigger's flex row", async () => {
    installStartedSession();
    renderLayout('/runs/run-1/details');

    const track = (await screen.findByRole('link', {name: 'Results'})).closest(
      'nav',
    );
    expect(track?.className).toContain('inline-grid');
    expect(track?.className).not.toContain('inline-flex');
  });

  it('is the same size as the Logs trigger it was built from', async () => {
    installStartedSession();
    renderLayout('/runs/run-1/details');

    const track = (await screen.findByRole('link', {name: 'Results'})).closest(
      'nav',
    );
    const logs = screen.getByRole('button', {name: /logs/i});
    for (const shared of ['h-[2.35rem]', 'rounded-full', 'text-[0.88rem]']) {
      expect(track?.className).toContain(shared);
      expect(logs.className).toContain(shared);
    }
    expect(track?.className).toContain('p-0');
    expect(screen.getByRole('link', {name: 'Chat'}).className).toContain(
      'px-[0.72rem]',
    );
    expect(logs.className).toContain('pl-[0.72rem]');
  });
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

  it('falls back to wherever the switch was last left', () => {
    writeSessionSide('run-1', 'chat');
    expect(preferredSessionSide('run-2')).toBe('chat');
  });

  it('prefers a session’s own memory over the switch’s last position', () => {
    writeSessionSide('run-1', 'chat');
    writeSessionSide('run-2', 'results');
    expect(preferredSessionSide('run-1')).toBe('chat');
  });

  it('has no opinion before the switch has ever been used', () => {
    expect(preferredSessionSide('run-1')).toBeUndefined();
    expect(preferredSessionSide(undefined)).toBeUndefined();
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

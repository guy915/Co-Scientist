import {screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  apiMock,
  chatFixture,
  installLayoutMocks,
  renderLayout,
} from './layout_test_support';

beforeEach(() => {
  installLayoutMocks();
});

// A session that has both halves: the conversation chat-7 and the run it
// started. Everything the switch renders is derived from this one record.
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
  // The results half marks itself as where the reader already is, so the
  // switch reads as a position rather than as two equal destinations.
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

  // Waits on the chat list so the assertion runs after the history load that
  // would have produced a switch, rather than before it.
  expect(await screen.findByText('Still deciding')).toBeInTheDocument();
  expect(screen.queryByRole('link', {name: 'Results'})).toBeNull();
});

// The accent belongs to the half you are on, not to the control. Filling the
// whole track with it left the highlight nothing to say, and the sides then
// had no colour of their own to state -- so the user agent's visited-link
// rule, which outranks an inherited colour, painted both labels purple once
// either had been followed.
it('spends the accent on the active half and colours both labels itself', async () => {
  installStartedSession();
  renderLayout('/runs/run-1/details');

  const results = await screen.findByRole('link', {name: 'Results'});
  const chat = screen.getByRole('link', {name: 'Chat'});
  const track = results.closest('nav');

  expect(track?.className).not.toContain('bg-cosci-logs-accent-bg');
  expect(track?.className).toContain('bg-cosci-settings-segment-bg');
  expect(results.className).toContain('bg-cosci-logs-accent-bg');
  expect(chat.className).not.toContain('bg-cosci-logs-accent-bg');
  // Neither side may fall back to the inherited colour.
  expect(results.className).toContain('text-cosci-logs-accent-fg');
  expect(chat.className).toContain('text-cosci-shell-icon');
});

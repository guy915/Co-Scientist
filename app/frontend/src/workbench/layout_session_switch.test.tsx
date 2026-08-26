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

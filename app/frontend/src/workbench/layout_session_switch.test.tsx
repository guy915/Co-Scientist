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
it('spends the accent on the sliding highlight and colours both labels itself', async () => {
  installStartedSession();
  renderLayout('/runs/run-1/details');

  const results = await screen.findByRole('link', {name: 'Results'});
  const chat = screen.getByRole('link', {name: 'Chat'});
  const track = results.closest('nav');

  // The fill is the highlight's, never a background on a side: only one
  // element can travel from where the marker was to where it is going.
  const thumb = track?.querySelector('.ucs-session-switch-thumb');
  expect(thumb).not.toBeNull();
  expect(track).toHaveAttribute('data-active', 'results');
  expect(track?.className).not.toContain('bg-cosci-logs-accent-bg');
  expect(results.className).not.toContain('bg-cosci-logs-accent-bg');
  expect(chat.className).not.toContain('bg-cosci-logs-accent-bg');
  // The quiet surface is an existing configured pair, not a colour
  // invented here.
  expect(track?.className).toContain('bg-cosci-recent-meta-bg');
  // Neither side may fall back to the inherited colour.
  expect(results.className).toContain('text-cosci-logs-accent-fg');
  expect(chat.className).toContain('text-cosci-shell-icon');
});

// `display` is deliberately absent from HEADER_PILL_SHAPE_CLASSES. Carrying
// `inline-flex` there silently outranked this track's own `grid` -- Tailwind
// resolves same-property utilities by stylesheet order, not class order --
// which left the halves content-sized at 80px and 97px, so the 50%-wide
// highlight lined up with neither.
it("keeps the track a two-column grid, not the trigger's flex row", async () => {
  installStartedSession();
  renderLayout('/runs/run-1/details');

  const track = (await screen.findByRole('link', {name: 'Results'})).closest(
    'nav',
  );
  expect(track?.className).toContain('inline-grid');
  expect(track?.className).not.toContain('inline-flex');
});

// The switch and the Logs trigger are the same control at the same size:
// same height, radius, type scale and horizontal padding, and no padding on
// the track, so a half is a full-height pill rather than a smaller one inset
// inside a taller box.
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
  // The trigger tightens its own right side around the count badge, so the
  // leading padding is the value the two actually share.
  expect(screen.getByRole('link', {name: 'Chat'}).className).toContain(
    'px-[0.72rem]',
  );
  expect(logs.className).toContain('pl-[0.72rem]');
});

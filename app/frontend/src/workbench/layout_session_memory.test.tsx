import {screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it} from 'vitest';
import {preferredSessionSide, writeSessionSide} from './layout_session_memory';
import {
  apiMock,
  chatFixture,
  installLayoutMocks,
  renderLayout,
} from './layout_test_support';

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

// The scientist reads the control as one switch with a position, not as a
// per-session preference. Flipping it to Chat and then opening a *different*
// session -- which has no memory of its own -- and landing on Results reads
// as the switch having been ignored, which is the complaint this answers.
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
  // A session the reader has never opened: without the fallback the rail
  // row goes to the run, whatever the switch was last set to.
  apiMock.listInterviews.mockResolvedValue([
    chatFixture('chat-7', 'Study pathway X', {run_id: 'run-1'}),
  ]);
  writeSessionSide('run-9', 'chat');
  renderLayout('/');

  expect(
    await screen.findByRole('link', {name: /Study pathway X/}),
  ).toHaveAttribute('href', '/chats/chat-7');
});

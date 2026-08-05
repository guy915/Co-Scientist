import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import type {StreamConnectionState} from '@/hooks/use_run_stream';
import {ActiveRunView} from './run_detail_active';
import type {RunWithStreamState} from './run_detail_data';
import {makeRun} from './run_detail_test_support';

function activeRun(connection?: StreamConnectionState): RunWithStreamState {
  return {
    ...makeRun('Study pathway X'),
    status: 'running',
    created_at: Date.now() / 1000 - 5,
    stream_connection: connection,
  };
}

function renderView(connection?: StreamConnectionState) {
  return render(
    <ActiveRunView
      run={activeRun(connection)}
      events={[]}
      evidenceCount={0}
      ideaCount={0}
    />,
  );
}

// The pulse dot is the "feed is live" claim; its ring is the only element
// carrying the ping animation.
function hasLivePulse(): boolean {
  return document.querySelector('.animate-ping') !== null;
}

it('shows the live pulse and no status note on an open stream', () => {
  renderView('open');
  expect(hasLivePulse()).toBe(true);
  expect(screen.queryByRole('status')).toBeNull();
});

it('surfaces a reconnecting stream instead of passing as healthy', () => {
  renderView('reconnecting');
  expect(hasLivePulse()).toBe(false);
  expect(screen.getByRole('status')).toHaveTextContent('Reconnecting...');
});

it('surfaces a stream that ended with no retry', () => {
  renderView('disconnected');
  expect(hasLivePulse()).toBe(false);
  expect(screen.getByRole('status')).toHaveTextContent('Stream disconnected');
});

it('names a stream that has not opened yet', () => {
  renderView('connecting');
  expect(hasLivePulse()).toBe(false);
  expect(screen.getByRole('status')).toHaveTextContent('Connecting...');
});

it('treats a missing transport state as no signal, not a drop', () => {
  // A stream double without the field (older test harnesses) must render
  // exactly as a healthy stream rather than as a degraded one.
  renderView(undefined);
  expect(hasLivePulse()).toBe(true);
  expect(screen.queryByRole('status')).toBeNull();
});

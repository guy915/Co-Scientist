import {render, screen, fireEvent} from '@testing-library/react';
import {expect, it, describe} from 'vitest';
import type {StreamConnectionState, StreamEvent} from '@/hooks/use_run_stream';
import {ActiveRunView} from './run_detail_active';
import type {RunWithStreamState} from './run_detail_data';
import {makeRun} from './run_detail_test_support';
import {windowedActivityGroups, ActivityLog} from './run_detail_activity_log';

describe('run detail active', () => {
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
        allocationLedger={{
          response: null,
          loading: false,
          error: null,
          onRetry: () => {},
        }}
      />,
    );
  }

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
    renderView(undefined);
    expect(hasLivePulse()).toBe(true);
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('run detail activity log', () => {
  const NOW = 1_000_000;

  function event(
    seq: number,
    payload: Record<string, unknown>,
    type = 'scientific_task',
  ): StreamEvent {
    return {seq, type, payload, created_at: NOW};
  }

  function renderLog(events: StreamEvent[]) {
    return render(
      <ActivityLog
        groups={windowedActivityGroups(events, 10)}
        connection="open"
        nowSeconds={NOW}
      />,
    );
  }

  it('renders the closed-vocabulary label when an event carries `activity`', () => {
    renderLog([event(1, {task: 'ranking', activity: 'tournament'})]);
    expect(screen.getByText('Comparing ideas')).toBeInTheDocument();
  });

  it('falls back to the legacy node-keyed table when `activity` is absent', () => {
    renderLog([event(1, {task: 'ranking'})]);
    expect(screen.getByText('Ranking tournament')).toBeInTheDocument();
    expect(screen.queryByText('Comparing ideas')).toBeNull();
  });

  it('collapses three consecutive same-activity events into one card', () => {
    renderLog([
      event(1, {task: 'ranking', activity: 'tournament'}),
      event(2, {task: 'ranking', activity: 'tournament'}),
      event(3, {task: 'ranking', activity: 'tournament'}),
    ]);
    expect(screen.getByText('Comparing ideas · 3 steps')).toBeInTheDocument();
    expect(screen.queryByText('Comparing ideas')).toBeNull();
  });

  it('splits a run into separate groups when a different activity interrupts it', () => {
    renderLog([
      event(1, {task: 'ranking', activity: 'tournament'}),
      event(2, {task: 'ranking', activity: 'tournament'}),
      event(3, {task: 'review', activity: 'review'}),
      event(4, {task: 'ranking', activity: 'tournament'}),
    ]);
    expect(screen.getByText('Comparing ideas · 2 steps')).toBeInTheDocument();
    expect(screen.getByText('Comparing ideas')).toBeInTheDocument();
    expect(screen.getByText('Reviewing hypotheses')).toBeInTheDocument();
  });

  it('expands a group to show its individual events', () => {
    renderLog([
      event(1, {task: 'ranking', activity: 'tournament', message: 'Match 1'}),
      event(2, {task: 'ranking', activity: 'tournament', message: 'Match 2'}),
    ]);
    expect(screen.queryByText('Match 1')).toBeNull();
    fireEvent.click(
      screen.getByRole('button', {name: '2 steps for Comparing ideas'}),
    );
    expect(screen.getByText('Match 1')).toBeInTheDocument();
    expect(screen.getByText('Match 2')).toBeInTheDocument();
  });

  it('reads the newest group as in progress, not an older one', () => {
    renderLog([
      event(1, {task: 'ranking', activity: 'tournament'}),
      event(2, {task: 'ranking', activity: 'tournament'}),
      event(3, {task: 'review', activity: 'review'}),
      event(4, {task: 'review', activity: 'review'}),
    ]);
    expect(screen.getAllByText('In progress')).toHaveLength(1);
  });
});

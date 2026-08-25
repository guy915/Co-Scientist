import {fireEvent, render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {windowedActivityGroups} from './run_detail_activity';
import {ActivityLog} from './run_detail_activity_log';

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
  // The fallback table names the ranking node specifically; the
  // closed-vocabulary title for the same node's activity must not appear,
  // proving this rendered through the fallback and not the new table.
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
  // Two separate tournament cards -- the interrupting review event must not
  // merge them into a single "4 steps" card.
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
  // Only the newest (review) group is still accumulating steps.
  expect(screen.getAllByText('In progress')).toHaveLength(1);
});

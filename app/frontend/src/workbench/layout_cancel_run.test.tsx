import {act, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {HttpError} from '@/api/runs';
import {RUNS_CHANGED_EVENT} from './dom_events';
import {CancelRunControl} from './layout_cancel_run';

const cancelRun = vi.hoisted(() => vi.fn());

vi.mock('@/api/runs', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/runs')>('@/api/runs');
  return {...actual, cancelRun};
});

beforeEach(() => {
  cancelRun.mockReset();
  cancelRun.mockResolvedValue({id: 'run-1', status: 'cancelled'});
});

afterEach(() => {
  vi.useRealTimers();
});

function renderControl(status: string | undefined, runId = 'run-1') {
  return render(
    <CancelRunControl
      runId={runId}
      status={status as Parameters<typeof CancelRunControl>[0]['status']}
    />,
  );
}

function stopButton() {
  return screen.getByRole('button', {name: /stop/i});
}

it.each(['running', 'paused'])('offers the control for a %s run', status => {
  renderControl(status);
  expect(stopButton()).toBeInTheDocument();
});

it.each([
  ['finished', 'completed', 'run-1'],
  ['never started a run', undefined, undefined],
  ['never started (draft)', 'draft', 'run-1'],
])('offers nothing for a session that %s', (_name, status, runId) => {
  renderControl(status, runId);
  expect(screen.queryByRole('button', {name: /stop/i})).toBeNull();
});

it('asks twice before stopping, since stopping cannot be undone', async () => {
  renderControl('running');

  fireEvent.click(stopButton());

  expect(cancelRun).not.toHaveBeenCalled();
  expect(
    screen.getByRole('button', {name: 'Confirm stop'}),
  ).toBeInTheDocument();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', {name: 'Confirm stop'}));
  });

  expect(cancelRun).toHaveBeenCalledWith('run-1');
});

it('disarms itself so a stale confirm cannot stop a run later', () => {
  vi.useFakeTimers();
  renderControl('running');

  fireEvent.click(stopButton());
  act(() => void vi.advanceTimersByTime(5_000));

  expect(screen.getByRole('button', {name: 'Stop run'})).toBeInTheDocument();
});

it('refreshes the run list after stopping, which is what hides it', async () => {
  const onChanged = vi.fn();
  window.addEventListener(RUNS_CHANGED_EVENT, onChanged);
  renderControl('running');

  fireEvent.click(stopButton());
  await act(async () => {
    fireEvent.click(screen.getByRole('button', {name: 'Confirm stop'}));
  });

  expect(onChanged).toHaveBeenCalled();
  window.removeEventListener(RUNS_CHANGED_EVENT, onChanged);
});

it('treats "already finished" as the list being stale, not as an error', async () => {
  // A run can finish between polling and cancellation; refreshing removes the
  // stale action.
  cancelRun.mockRejectedValue(new HttpError('run already finished', 409));
  const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
  const onChanged = vi.fn();
  window.addEventListener(RUNS_CHANGED_EVENT, onChanged);
  renderControl('running');

  fireEvent.click(stopButton());
  await act(async () => {
    fireEvent.click(screen.getByRole('button', {name: 'Confirm stop'}));
  });

  expect(onChanged).toHaveBeenCalled();
  expect(errors).not.toHaveBeenCalled();
  window.removeEventListener(RUNS_CHANGED_EVENT, onChanged);
  errors.mockRestore();
});

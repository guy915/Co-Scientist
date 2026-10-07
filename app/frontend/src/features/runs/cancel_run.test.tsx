import {act, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {HttpError} from '@/shared/api/runs';
import {RUNS_CHANGED_EVENT} from '@/shared/lib/dom_events';
import {CancelRunControl} from './cancel_run';

const cancelRun = vi.hoisted(() => vi.fn());

vi.mock('@/shared/api/runs', async () => {
  const actual =
    await vi.importActual<typeof import('@/shared/api/runs')>('@/shared/api/runs');
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

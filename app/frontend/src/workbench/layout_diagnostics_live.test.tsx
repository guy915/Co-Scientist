import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';
import {
  logRecord,
  settleMountTimeLoads,
  stubListGeometry,
} from './layout_diagnostics_test_support';

beforeEach(() => installLayoutMocks());

it('ignores stale out-of-order log responses', async () => {
  const payload = (id: number) => ({
    logs: [logRecord(id)],
    last_id: id,
    total: id,
  });
  // Let the mount-time loads settle first, so both racing requests
  // below belong to the same effect generation.
  renderLayout();
  await settleMountTimeLoads();

  // The next request hangs (stale); the one after answers fresh. The
  // stale response then arrives LAST and must be dropped.
  let resolveStale: (value: unknown) => void = () => {};
  const hanging = new Promise(resolve => {
    resolveStale = resolve;
  });
  logsApiMock.getAppLogs
    .mockReturnValueOnce(hanging)
    .mockResolvedValue(payload(2));

  const {APP_LOGS_CHANGED_EVENT} = await import('@/api/logs');
  fireEvent(window, new Event(APP_LOGS_CHANGED_EVENT));
  fireEvent(window, new Event(APP_LOGS_CHANGED_EVENT));
  await screen.findByRole('button', {name: /Logs 2/i});

  resolveStale(payload(1));
  await act(async () => {
    // give the stale response a real window to (wrongly) land
    await new Promise(resolve => setTimeout(resolve, 20));
  });
  // The late stale response did not overwrite the fresher one.
  expect(screen.queryByRole('button', {name: /Logs 1$/})).toBeNull();
  expect(screen.getByRole('button', {name: /Logs 2/i})).toBeInTheDocument();
});

it('does not jump to the end while the user is scrolled up', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [logRecord(1), logRecord(2)],
    last_id: 2,
    total: 2,
  });
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
  const list = await screen.findByLabelText('Log events');

  // Simulate a scrollable list with the user scrolled well above the
  // bottom.
  stubListGeometry(list);
  list.scrollTop = 100;
  fireEvent.scroll(list);

  // New records arrive (an in-page event bumps the fetch version).
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [logRecord(1), logRecord(2), logRecord(3)],
    last_id: 3,
    total: 3,
  });
  fireEvent(
    window,
    new CustomEvent(DIAGNOSTIC_EVENT, {
      detail: {stage: 'LIFECYCLE', level: 'info', payload: {}},
    }),
  );
  await screen.findByText(/record 3/);

  // Reading position is preserved; only opening the popover jumps down.
  expect(list.scrollTop).toBe(100);
});

it('keeps following the newest record at the window cap when pinned', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [logRecord(1), logRecord(2)],
    last_id: 2,
    total: 2,
  });
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
  const list = await screen.findByLabelText('Log events');

  stubListGeometry(list);
  list.scrollTop = 900; // at the bottom: pinned
  fireEvent.scroll(list);

  // The window is at its cap: a new record replaces the oldest, so the
  // entry COUNT stays the same and only the ids advance. Auto-follow
  // must still fire for the pinned reader.
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [logRecord(2), logRecord(3)],
    last_id: 3,
    total: 3,
  });
  fireEvent(
    window,
    new CustomEvent(DIAGNOSTIC_EVENT, {
      detail: {stage: 'LIFECYCLE', level: 'info', payload: {}},
    }),
  );
  await screen.findByText(/record 3/);

  // waitFor: the scroll happens in a passive effect after the render
  // that findByText observed.
  await waitFor(() => expect(list.scrollTop).toBe(1000));
});

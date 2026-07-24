import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {logRecord} from './layout_diagnostics_test_support';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

beforeEach(() => installLayoutMocks());

it('hides pre-session history and shows only records added this session', async () => {
  // The panel is a per-page-session view of the durable, app-wide log:
  // whatever history already exists when the page loads is hidden, so a
  // refresh or reopen starts clean. Only records added afterwards appear.
  logsApiMock.getAppLogs.mockReset();
  // First load (after_id=0): the retained history at session start. It
  // anchors the baseline and must not be shown.
  logsApiMock.getAppLogs.mockResolvedValueOnce({
    logs: [
      logRecord(98, {message: 'stale line from before'}),
      logRecord(99, {message: 'another old line'}),
      logRecord(100, {message: 'newest pre-session line'}),
    ],
    last_id: 100,
    total: 5,
  });
  // Every later load pages from the baseline (after_id=100): the server
  // returns only the one record added this session.
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [logRecord(101, {message: 'fresh session line'})],
    last_id: 101,
    total: 6,
  });

  renderLayout('/');
  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));

  // The one this-session record shows, numbered from 1; the pre-session
  // history is gone.
  expect(await screen.findByText(/fresh session line/)).toBeInTheDocument();
  expect(screen.queryByText(/stale line from before/)).toBeNull();
  expect(screen.queryByText(/newest pre-session line/)).toBeNull();
  const meta = document.querySelector('.ucs-diagnostic-entry-meta span');
  expect(meta?.textContent).toBe('#1');
  expect(screen.getByText('Total 1')).toBeInTheDocument();
  // Pages from the captured baseline, never the whole retained log.
  expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(100, 100);
});

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

it('keeps this session across a tab reload', async () => {
  // A reload is the reflex for "did that just get logged?" — it must not
  // throw the session away. The baseline lives in sessionStorage, so a
  // fresh page load of the same tab resumes from where the session began
  // instead of re-anchoring to the current high-water id (which would
  // hide everything logged so far).
  window.sessionStorage.setItem(
    'cosci-logs-session-baseline',
    JSON.stringify({id: 100, total: 5}),
  );
  logsApiMock.getAppLogs.mockReset();
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      logRecord(101, {message: 'logged before the reload'}),
      logRecord(102, {message: 'logged after the reload'}),
    ],
    last_id: 102,
    total: 7,
  });

  renderLayout('/');
  fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));

  expect(await screen.findByText(/logged before the reload/)).toBeVisible();
  expect(screen.getByText(/logged after the reload/)).toBeVisible();
  // Numbering continues from the session's start, not from this load.
  expect(screen.getByText('Total 2')).toBeInTheDocument();
  expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(100, 100);
});

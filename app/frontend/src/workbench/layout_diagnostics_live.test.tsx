import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, describe} from 'vitest';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
  systemApiMock,
} from './layout_test_support';
import {
  logRecord,
  settleMountTimeLoads,
  stubListGeometry,
} from './layout_diagnostics_test_support';

describe('layout diagnostics live', () => {
  beforeEach(() => installLayoutMocks());

  it('ignores stale out-of-order log responses', async () => {
    const payload = (id: number) => ({
      logs: [logRecord(id)],
      last_id: id,
      total: id,
      session_total: id,
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
      session_total: 2,
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
      session_total: 3,
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

  it('keeps following the newest record at the window cap', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [logRecord(1), logRecord(2)],
      last_id: 2,
      total: 2,
      session_total: 2,
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
      session_total: 3,
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
});

describe('layout diagnostic events', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('never persists goal text as a run id', async () => {
    renderLayout();

    // Callers used to pass a goal-derived title as `run`, which was
    // stored in the run_id column and served over the API. Only a real
    // run id may become run_id; a display title is ignored.
    fireEvent(
      window,
      new CustomEvent(DIAGNOSTIC_EVENT, {
        detail: {
          stage: 'LIFECYCLE',
          run: 'Novel oncology target X in pancreatic cancer',
          level: 'info',
          payload: {event: 'start_requested'},
        },
      }),
    );

    await waitFor(() => expect(logsApiMock.postAppLogs).toHaveBeenCalled());
    const posted = logsApiMock.postAppLogs.mock.calls
      .flatMap(call => call[0] as {message: string; run_id?: string}[])
      .filter(record => record.message.startsWith('LIFECYCLE'));
    expect(posted).toHaveLength(1);
    expect(posted[0].run_id).toBeUndefined();
    expect(JSON.stringify(posted[0])).not.toContain('oncology');
  });

  it('ships in-page diagnostic events to the persisted log', async () => {
    renderLayout();

    fireEvent(
      window,
      new CustomEvent(DIAGNOSTIC_EVENT, {
        detail: {
          stage: 'LIFECYCLE',
          runId: 'run-abc',
          level: 'info',
          payload: {event: 'draft_created'},
        },
      }),
    );

    // The event is POSTed to the app-wide log rather than kept in memory,
    // so it survives reloads and is visible to the CLI and other tabs.
    await waitFor(() =>
      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {
          message: 'LIFECYCLE {"event":"draft_created"}',
          level: 'info',
          logger: 'session',
          run_id: 'run-abc',
        },
      ]),
    );
  });

  it('persists route navigation into the log', async () => {
    renderLayout('/');

    await waitFor(() =>
      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {message: 'page loaded at /', logger: 'navigation'},
      ]),
    );
  });
});

describe('layout diagnostics report', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  // The panel only offers Report where the server can actually send mail.
  function withEmailDelivery() {
    systemApiMock.getSystemStatus.mockResolvedValue({
      llm_backend: 'real',
      provider: 'engine',
      model_name: 'test/model',
      email_notifications_available: true,
    });
  }

  async function openReportButton() {
    fireEvent.click(screen.getByRole('button', {name: /Logs/i}));
    const button = await screen.findByRole('button', {name: /Report/});
    await waitFor(() => expect(button).toBeEnabled());
    return button;
  }

  it('sends the same export the Copy button produces', async () => {
    withEmailDelivery();
    renderLayout();

    fireEvent.click(await openReportButton());

    await waitFor(() =>
      expect(logsApiMock.reportAppLogs).toHaveBeenCalledOnce(),
    );
    // The whole self-describing document, not a pointer to it: the panel's
    // view is anchored to this browsing session, so a link would not
    // reproduce what the scientist was looking at.
    const [report] = logsApiMock.reportAppLogs.mock.calls[0] as [string];
    expect(report).toContain('=== LOGS (JSON) ===');
    expect(await screen.findByText('Sent')).toBeInTheDocument();
  });

  it('says so when the report could not be sent', async () => {
    withEmailDelivery();
    logsApiMock.reportAppLogs.mockRejectedValue(new Error('503'));
    renderLayout();

    fireEvent.click(await openReportButton());

    // A report that silently did not arrive is worse than no button: the
    // scientist stops looking for another way to tell anyone.
    expect(await screen.findByText("Couldn't send")).toBeInTheDocument();
  });
});

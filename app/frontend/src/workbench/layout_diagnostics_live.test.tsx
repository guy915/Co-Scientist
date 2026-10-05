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
    // Settle mount loads so racing requests share an effect generation rather
    // than disposal guards.
    renderLayout();
    await settleMountTimeLoads();

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
      await new Promise(resolve => setTimeout(resolve, 20));
    });
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

    stubListGeometry(list);
    list.scrollTop = 100;
    fireEvent.scroll(list);

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

    expect(list.scrollTop).toBe(100);
  });
});

describe('layout diagnostic events', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('never persists goal text as a run id', async () => {
    renderLayout();

    // Display titles must not be stored as run_id.
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
    // Session-scoped log views cannot be reproduced by a link alone.
    const [report] = logsApiMock.reportAppLogs.mock.calls[0] as [string];
    expect(report).toContain('=== LOGS (JSON) ===');
    expect(await screen.findByText('Sent')).toBeInTheDocument();
  });

  it('says so when the report could not be sent', async () => {
    withEmailDelivery();
    logsApiMock.reportAppLogs.mockRejectedValue(new Error('503'));
    renderLayout();

    fireEvent.click(await openReportButton());

    expect(await screen.findByText("Couldn't send")).toBeInTheDocument();
  });
});

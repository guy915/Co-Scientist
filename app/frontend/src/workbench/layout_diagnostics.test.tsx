import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
  systemApiMock,
} from './layout_test_support';
// Import after layout_test_support, whose module mock must be registered
// before the real API module loads.
import {APP_LOGS_CHANGED_EVENT} from '@/api/logs';
import {exportedRecords} from '@/test_fixtures';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {COPY_LIMIT} from './layout_diagnostics_data';
import {
  logRecord,
  settleMountTimeLoads,
} from './layout_diagnostics_test_support';

// The badge only counts records that arrive after the mount-time load fixes
// the session baseline, and the next load comes from a poll or this event.
// Waiting on the poll or on a mount-time event races that listener under load.
async function renderWithLogsLoaded() {
  renderLayout();
  await settleMountTimeLoads();
  await act(async () => {
    window.dispatchEvent(new Event(APP_LOGS_CHANGED_EVENT));
  });
}

describe('layout diagnostics panel', () => {
  beforeEach(() => installLayoutMocks());

  it('renders the message as plain text with a level meta row', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        logRecord(1, {message: 'a long message that must wrap freely'}),
        logRecord(2, {
          level: 'ERROR',
          levelno: 40,
          logger: 'app.engine_adapter',
          message: 'workflow exploded',
          exc_text: 'Traceback: boom',
        }),
      ],
      last_id: 2,
      total: 2,
      session_total: 2,
    });
    const {container} = renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
    await screen.findByText(/wrap freely/);

    const blocks = container.querySelectorAll('.ucs-diagnostic-entry pre');
    expect(blocks).toHaveLength(2);
    expect(blocks[0].textContent).toBe('a long message that must wrap freely');
    expect(blocks[1].textContent).toBe('workflow exploded\n\nTraceback: boom');
    expect(screen.getByText('INFO')).toBeInTheDocument();
    expect(screen.getByText('ERROR')).toBeInTheDocument();
  });
});

describe('layout diagnostics session', () => {
  beforeEach(() => installLayoutMocks());

  it('hides pre-session history and shows only records added this session', async () => {
    logsApiMock.getAppLogs.mockReset();
    logsApiMock.getAppLogs.mockResolvedValueOnce({
      logs: [
        logRecord(98, {message: 'stale line from before'}),
        logRecord(99, {message: 'another old line'}),
        logRecord(100, {message: 'newest pre-session line'}),
      ],
      last_id: 100,
      total: 5,
      session_total: 5,
    });
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [logRecord(101, {message: 'fresh session line'})],
      last_id: 101,
      total: 6,
      session_total: 1,
    });

    renderLayout('/');
    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));

    expect(await screen.findByText(/fresh session line/)).toBeInTheDocument();
    expect(screen.queryByText(/stale line from before/)).toBeNull();
    expect(screen.queryByText(/newest pre-session line/)).toBeNull();
    const meta = document.querySelector('.ucs-diagnostic-entry-meta span');
    expect(meta?.textContent).toBe('#1');
    expect(screen.getByText('Total 1')).toBeInTheDocument();
    expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(100, 100);
  });
});

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
    expect(report).toContain('## Logs (JSON)');
    expect(await screen.findByText('Sent')).toBeInTheDocument();
  });
});

describe('layout diagnostics copy', () => {
  beforeEach(() => installLayoutMocks());
  afterEach(() => vi.useRealTimers());

  it('clears the persisted log from the Clear action', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        logRecord(1, {created_at: 1_700_000_000, message: 'server started'}),
      ],
      last_id: 1,
      total: 1,
      session_total: 1,
    });
    await renderWithLogsLoaded();

    fireEvent.click(
      await screen.findByRole('button', {name: /Logs 1/i}, {timeout: 5_000}),
    );
    expect(await screen.findByText(/server started/)).toBeInTheDocument();

    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [],
      last_id: 1,
      total: 0,
      session_total: 0,
    });
    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));

    await waitFor(() => expect(logsApiMock.deleteAppLogs).toHaveBeenCalled());
    expect(
      await screen.findByText('No diagnostic events loaded.'),
    ).toBeInTheDocument();
  });

  it('copies the newest COPY_LIMIT entries, not the whole session', async () => {
    const many = Array.from({length: 140}, (_, index) =>
      logRecord(index + 1, {created_at: 1_700_000_000 + index}),
    );
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: many,
      last_id: 140,
      total: 140,
      session_total: 140,
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {clipboard: {writeText}});
    await renderWithLogsLoaded();

    fireEvent.click(
      await screen.findByRole('button', {name: /Logs 140/i}, {timeout: 5_000}),
    );
    await screen.findByText(/record 140/);
    fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const copied = exportedRecords(writeText.mock.calls[0][0] as string) as {
      payload: {message: string};
    }[];
    expect(copied).toHaveLength(COPY_LIMIT);
    expect(copied[0].payload.message).toBe('record 41');
    expect(copied[COPY_LIMIT - 1].payload.message).toBe('record 140');
  });
});

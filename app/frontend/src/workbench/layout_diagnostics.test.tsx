import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  logRecord,
  settleMountTimeLoads,
} from './layout_diagnostics_test_support';

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

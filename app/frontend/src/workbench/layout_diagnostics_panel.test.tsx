import {makeLogRecord as logRecord} from '@/test_fixtures';
import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, describe} from 'vitest';
import {
  apiMock,
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

describe('layout diagnostics panel', () => {
  beforeEach(() => installLayoutMocks());

  it('shows the same app-wide log on a run route as on home', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        logRecord(41, {created_at: 1_700_000_000, message: 'server started'}),
      ],
      last_id: 41,
      total: 1,
      session_total: 1,
    });
    renderLayout('/runs/demo-ferroptosis/ideas');

    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));

    expect(await screen.findByText(/server started/)).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(apiMock.getRunEvents).not.toHaveBeenCalled();
  });

  it('loads persisted backend logs into the diagnostics popover', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        logRecord(3, {
          level: 'ERROR',
          levelno: 40,
          logger: 'app.engine_adapter',
          message: 'workflow exploded',
        }),
        logRecord(4, {
          logger: 'app.runs',
          message: 'run started',
          run_id: 'run-12345678',
        }),
        logRecord(5, {
          level: 'WARNING',
          levelno: 30,
          logger: 'app.diagnostics',
          message: 'mcp probe unreachable',
        }),
      ],
      last_id: 5,
      total: 3,
      session_total: 3,
    });
    renderLayout('/');

    fireEvent.click(screen.getByRole('button', {name: /Logs 0/i}));

    await waitFor(() => expect(logsApiMock.getAppLogs).toHaveBeenCalled());
    expect(await screen.findByText('app.engine_adapter:')).toBeInTheDocument();
    expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
    expect(screen.getAllByText('Server')).toHaveLength(2);
    expect(screen.getByText('Run run-1234')).toBeInTheDocument();
    expect(screen.getByText('Errors 1')).toBeInTheDocument();
    expect(screen.getByText('Warnings 1')).toBeInTheDocument();
    expect(screen.getByText('Info 1')).toBeInTheDocument();
    expect(screen.getByText('Total 3')).toBeInTheDocument();
    expect(screen.getByText('1 run')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));
    expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
  });

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

describe('layout diagnostics numbering', () => {
  beforeEach(() => installLayoutMocks());

  it('renumbers shown records consecutively, ignoring id gaps', async () => {
    // Global store ids include filtered noise; contiguous display numbers avoid
    // apparent missing rows.
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [12, 13, 30, 31].map(id => logRecord(id)),
      last_id: 33,
      total: 4,
      session_total: 4,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 4/i}));
    await screen.findByText(/record 12/);

    const numbers = Array.from(
      document.querySelectorAll('.ucs-diagnostic-entry-meta'),
    ).map(el => el.querySelector('span')?.textContent);
    expect(numbers).toEqual(['#1', '#2', '#3', '#4']);
    expect(await screen.findByText('Total 4')).toBeInTheDocument();
    expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(0, 100);
  });

  it('numbers a capped window by position in the stream', async () => {
    const logs = Array.from({length: 100}, (_, index) =>
      logRecord(1000 + index * 3, {
        created_at: 1_700_000_000 + index,
        message: `record ${index}`,
      }),
    );
    logsApiMock.getAppLogs.mockResolvedValue({
      logs,
      last_id: 5000,
      total: 250,
      session_total: 250,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 250/i}));
    await screen.findByText(/record 99/);

    const metas = document.querySelectorAll('.ucs-diagnostic-entry-meta');
    expect(metas[0].querySelector('span')?.textContent).toBe('#151');
    expect(metas[99].querySelector('span')?.textContent).toBe('#250');

    expect(screen.getByText('Total 250')).toBeInTheDocument();
    expect(screen.getByText('Showing 100')).toBeInTheDocument();
    expect(screen.getByText('Info 100')).toBeInTheDocument();
  });

  it('omits the Showing chip when the bands already sum to the total', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        {
          id: 4,
          created_at: 1_700_000_000,
          level: 'WARNING',
          levelno: 30,
          logger: 'app.main',
          message: 'a lone warning',
          run_id: null,
          exc_text: null,
        },
      ],
      last_id: 4,
      total: 1,
      session_total: 1,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
    await screen.findByText(/a lone warning/);

    expect(screen.queryByText(/^Showing /)).toBeNull();
    expect(screen.getByText('0 runs')).toBeInTheDocument();
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

  it('keeps counting after pruning shrinks the whole-table total', async () => {
    // Pruning deletes rows below anchors; use after-cursor counts rather than
    // snapshot subtraction.
    window.sessionStorage.setItem(
      'cosci-logs-session-baseline',
      JSON.stringify({id: 100}),
    );
    logsApiMock.getAppLogs.mockReset();
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        logRecord(101, {message: 'survived the prune'}),
        logRecord(102, {message: 'logged after the prune'}),
      ],
      last_id: 102,
      total: 2,
      session_total: 2,
    });

    renderLayout('/');
    fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));

    expect(await screen.findByText(/survived the prune/)).toBeVisible();
    const numbers = Array.from(
      document.querySelectorAll('.ucs-diagnostic-entry-meta'),
    ).map(el => el.querySelector('span')?.textContent);
    expect(numbers).toEqual(['#1', '#2']);
    expect(screen.getByText('Total 2')).toBeInTheDocument();
  });
});

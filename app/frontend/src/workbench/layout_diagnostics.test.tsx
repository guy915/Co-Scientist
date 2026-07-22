import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {AppLogRecord} from '@/api/logs';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  apiMock,
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_utils';

function logRecord(
  id: number,
  overrides: Partial<AppLogRecord> = {},
): AppLogRecord {
  return {
    id,
    created_at: 1_700_000_000 + id,
    level: 'INFO',
    levelno: 20,
    logger: 'app.main',
    message: `record ${id}`,
    run_id: null,
    exc_text: null,
    ...overrides,
  };
}

/** jsdom does no layout, so the list's scroll geometry is stubbed. */
function stubListGeometry(list: HTMLElement): void {
  Object.defineProperty(list, 'scrollHeight', {
    configurable: true,
    value: 1000,
  });
  Object.defineProperty(list, 'clientHeight', {
    configurable: true,
    value: 100,
  });
}

/**
 * Waits for the mount-time log loads to settle — including the remount
 * caused by the navigation-log version bump — so racing requests issued
 * afterwards belong to the same effect generation (the `disposed` guard
 * must not be what saves us).
 */
async function settleMountTimeLoads(): Promise<void> {
  await waitFor(() =>
    expect(logsApiMock.getAppLogs.mock.calls.length).toBeGreaterThanOrEqual(2),
  );
  await act(async () => {
    // let the remounted effect finish its initial load
  });
}

describe('Layout diagnostics popover', () => {
  beforeEach(() => installLayoutMocks());

  it('clears the persisted log from the Clear action', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        {
          id: 1,
          created_at: 1_700_000_000,
          level: 'INFO',
          levelno: 20,
          logger: 'app.main',
          message: 'server started',
          run_id: null,
          exc_text: null,
        },
      ],
      last_id: 1,
      total: 1,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
    expect(await screen.findByText(/server started/)).toBeInTheDocument();

    logsApiMock.getAppLogs.mockResolvedValue({logs: [], last_id: 1, total: 0});
    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));

    // Clear deletes server-side, not just in this tab's memory.
    await waitFor(() => expect(logsApiMock.deleteAppLogs).toHaveBeenCalled());
    expect(
      await screen.findByText('No diagnostic events loaded.'),
    ).toBeInTheDocument();
  });

  it('copies only the newest 50 entries', async () => {
    const many = Array.from({length: 60}, (_, index) => ({
      id: index + 1,
      created_at: 1_700_000_000 + index,
      level: 'INFO',
      levelno: 20,
      logger: 'app.main',
      message: `record ${index + 1}`,
      run_id: null,
      exc_text: null,
    }));
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: many,
      last_id: 60,
      total: 60,
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {clipboard: {writeText}});
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 60/i}));
    // The full window loads when the popover opens; Copy reads it.
    await screen.findByText(/record 60/);
    fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const copied = JSON.parse(writeText.mock.calls[0][0] as string);
    expect(copied).toHaveLength(50);
    // The newest tail, not the oldest head.
    expect(copied[0].payload.message).toBe('record 11');
    expect(copied[49].payload.message).toBe('record 60');
  });

  it('opens the diagnostics panel with dark-mode shell styling', () => {
    const {container} = renderLayout();

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(document.documentElement).toHaveClass('dark');

    const logsButton = screen.getByRole('button', {name: /Logs 0/i});
    expect(logsButton.className).toContain('bg-cosci-logs-accent-bg');

    fireEvent.click(logsButton);

    const logsPopover = container.querySelector('.ucs-popover--logs');
    expect(logsPopover?.className).toContain('!bg-cosci-logs-surface');
    expect(screen.getByText('Diagnostic Logs')).toBeInTheDocument();
  });

  it('shows the same app-wide log on a run route as on home', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        {
          id: 41,
          created_at: 1_700_000_000,
          level: 'INFO',
          levelno: 20,
          logger: 'app.main',
          message: 'server started',
          run_id: null,
          exc_text: null,
        },
      ],
      last_id: 41,
      total: 1,
    });
    renderLayout('/runs/demo-ferroptosis/ideas');

    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));

    // Entering a run subpage must not swap the log for a run-scoped view:
    // the panel is the app-wide stream everywhere.
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
      ],
      last_id: 4,
      total: 2,
    });
    renderLayout('/');

    fireEvent.click(screen.getByRole('button', {name: /Logs 0/i}));

    // The popover fetches the app-wide persisted log on open, even with no
    // run in scope (that is the point: capture is app-wide).
    await waitFor(() => expect(logsApiMock.getAppLogs).toHaveBeenCalled());
    expect(await screen.findByText('app.engine_adapter:')).toBeInTheDocument();
    expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
    // Records with no run id are attributed to the server itself.
    expect(screen.getByText('Server')).toBeInTheDocument();
    expect(screen.getByText('Run run-1234')).toBeInTheDocument();
    // ERROR-level records count into the Errors chip.
    expect(screen.getByText('Errors 1')).toBeInTheDocument();

    // Clear drops only session entries; persisted backend logs remain.
    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));
    expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
  });

  it('renumbers shown records consecutively, ignoring store id gaps', async () => {
    // Store ids are global and include filtered-out noise, so a
    // filtered view has holes (#12, #13, #30, #31) that read as failed
    // renders. The panel numbers what it shows instead.
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [12, 13, 30, 31].map(id => ({
        id,
        created_at: 1_700_000_000 + id,
        level: 'INFO',
        levelno: 20,
        logger: 'app.main',
        message: `record ${id}`,
        run_id: null,
        exc_text: null,
      })),
      last_id: 33,
      total: 4,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 4/i}));
    await screen.findByText(/record 12/);

    const numbers = Array.from(
      document.querySelectorAll('.ucs-diagnostic-entry-meta'),
    ).map(el => el.querySelector('span')?.textContent);
    expect(numbers).toEqual(['#1', '#2', '#3', '#4']);
    // The badge is the newest row's number, so header and list agree.
    expect(await screen.findByText('Total 4')).toBeInTheDocument();
    expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(0, 100);
  });

  it('numbers a capped window by position in the whole filtered stream', async () => {
    // 250 records match the filter but only the newest 100 are fetched:
    // those are records 151..250, not 1..100.
    const logs = Array.from({length: 100}, (_, index) => ({
      id: 1000 + index * 3,
      created_at: 1_700_000_000 + index,
      level: 'INFO',
      levelno: 20,
      logger: 'app.main',
      message: `record ${index}`,
      run_id: null,
      exc_text: null,
    }));
    logsApiMock.getAppLogs.mockResolvedValue({
      logs,
      last_id: 5000,
      total: 250,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 250/i}));
    await screen.findByText(/record 99/);

    const metas = document.querySelectorAll('.ucs-diagnostic-entry-meta');
    expect(metas[0].querySelector('span')?.textContent).toBe('#151');
    expect(metas[99].querySelector('span')?.textContent).toBe('#250');
  });

  it('copies the real store ids, not the display numbers', async () => {
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [12, 30].map(id => ({
        id,
        created_at: 1_700_000_000 + id,
        level: 'INFO',
        levelno: 20,
        logger: 'app.main',
        message: `record ${id}`,
        run_id: null,
        exc_text: null,
      })),
      last_id: 33,
      total: 2,
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {clipboard: {writeText}});
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
    // The full window loads when the popover opens; Copy reads it.
    await screen.findByText(/record 30/);
    fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const copied = JSON.parse(writeText.mock.calls[0][0] as string);
    // Copy stays cross-referenceable with `cosci logs` and after_id
    // cursors, which speak store ids.
    expect(copied.map((e: {id: number}) => e.id)).toEqual([12, 30]);
    expect(copied.map((e: {number: number}) => e.number)).toEqual([1, 2]);
  });

  it('never shows more than the 100 newest records', async () => {
    // The fetch already asks for 100, but the panel enforces the cap
    // itself too: even an oversized payload renders as the newest 100.
    const many = Array.from({length: 120}, (_, index) => ({
      id: index + 1,
      created_at: 1_700_000_000 + index,
      level: 'INFO',
      levelno: 20,
      logger: 'app.main',
      message: `record ${index + 1}`,
      run_id: null,
      exc_text: null,
    }));
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: many,
      last_id: 120,
      total: 120,
    });
    const {container} = renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 120/i}));
    await screen.findByText(/record 120/);

    const entries = container.querySelectorAll('.ucs-diagnostic-entry');
    expect(entries).toHaveLength(100);
    // The newest 100 (21..120), not the oldest.
    expect(screen.queryByText(/record 20$/)).toBeNull();
    expect(entries[0].textContent).toContain('#21');
  });

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

  it('renders the message as plain text with the level in the meta row', async () => {
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
    });
    const {container} = renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
    await screen.findByText(/wrap freely/);

    const blocks = container.querySelectorAll('.ucs-diagnostic-entry pre');
    expect(blocks).toHaveLength(2);
    // No JSON scaffolding: the block is the message itself, and a
    // traceback follows on its own lines.
    expect(blocks[0].textContent).toBe('a long message that must wrap freely');
    expect(blocks[1].textContent).toBe('workflow exploded\n\nTraceback: boom');
    // The level moved to the meta row instead of a payload field.
    expect(screen.getByText('INFO')).toBeInTheDocument();
    expect(screen.getByText('ERROR')).toBeInTheDocument();
    // The block grows with its content: text wraps, nothing scrolls.
    expect(blocks[0].className).toContain('whitespace-pre-wrap');
    expect(blocks[0].className).not.toContain('overflow-auto');
    expect(blocks[0].className).not.toContain('max-h');
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
});

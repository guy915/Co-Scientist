import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, describe} from 'vitest';
import {
  apiMock,
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';
import {logRecord} from './layout_diagnostics_test_support';

describe('layout diagnostics panel', () => {
  beforeEach(() => installLayoutMocks());

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
      session_total: 1,
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

    // The popover fetches the app-wide persisted log on open, even with no
    // run in scope (that is the point: capture is app-wide).
    await waitFor(() => expect(logsApiMock.getAppLogs).toHaveBeenCalled());
    expect(await screen.findByText('app.engine_adapter:')).toBeInTheDocument();
    expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
    // Records with no run id are attributed to the server itself.
    expect(screen.getAllByText('Server')).toHaveLength(2);
    expect(screen.getByText('Run run-1234')).toBeInTheDocument();
    // The chips split the levels the way the rows print them: WARNING is its
    // own band, not folded into Errors, so a run that only warned does not
    // read as a run that failed.
    expect(screen.getByText('Errors 1')).toBeInTheDocument();
    expect(screen.getByText('Warnings 1')).toBeInTheDocument();
    expect(screen.getByText('Info 1')).toBeInTheDocument();
    // The three bands above are the whole list, so they sum to it.
    expect(screen.getByText('Total 3')).toBeInTheDocument();
    // The two server records remain in the list, but the run chip reflects
    // only the one record that belongs to a real research run -- and is
    // written as a noun, since it counts runs rather than records and must
    // not read as a fourth band of the sum beside it.
    expect(screen.getByText('1 run')).toBeInTheDocument();

    // Clear drops only session entries; persisted backend logs remain.
    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));
    expect(screen.getByText(/workflow exploded/)).toBeInTheDocument();
  });

  it('never scrolls sideways, even with a long logger name', async () => {
    // A long dotted logger name in the stage column used to widen the meta
    // grid past the panel and add a horizontal scrollbar. The list clips the
    // x-axis and the stage cell truncates, so only the y-axis can scroll.
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        logRecord(1, {
          logger:
            'co_scientist.agents.generation.literature_review.search_support',
          message: 'a very long line that would otherwise widen the panel body',
        }),
      ],
      last_id: 1,
      total: 1,
      session_total: 1,
    });
    const {container} = renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
    await screen.findByText(/widen the panel body/);

    const list = container.querySelector('.ucs-diagnostic-list');
    expect(list?.className).toContain('overflow-x-hidden');
    expect(list?.className).not.toContain('overflow-auto');
    const stage = container.querySelector('.ucs-diagnostic-entry-meta strong');
    expect(stage?.className).toContain('truncate');
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
});

describe('layout diagnostics numbering', () => {
  beforeEach(() => installLayoutMocks());

  it('renumbers shown records consecutively, ignoring id gaps', async () => {
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
      session_total: 4,
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

  it('numbers a capped window by position in the stream', async () => {
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
      session_total: 250,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 250/i}));
    await screen.findByText(/record 99/);

    const metas = document.querySelectorAll('.ucs-diagnostic-entry-meta');
    expect(metas[0].querySelector('span')?.textContent).toBe('#151');
    expect(metas[99].querySelector('span')?.textContent).toBe('#250');

    // The level bands tally the fetched window, not the whole stream, so a
    // capped window says so rather than quietly failing to sum to Total.
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
    // No run owns this record, so the run chip is zero — and reads as "0
    // runs" rather than as a band that would make the row fail to add up.
    expect(screen.getByText('0 runs')).toBeInTheDocument();
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
      session_total: 120,
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
});

describe('layout diagnostics session', () => {
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
      session_total: 5,
    });
    // Every later load pages from the baseline (after_id=100): the server
    // returns only the one record added this session, and counts only it.
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [logRecord(101, {message: 'fresh session line'})],
      last_id: 101,
      total: 6,
      session_total: 1,
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

  it('keeps counting after pruning shrinks the whole-table total', async () => {
    // Retention pruning and a scoped clear both delete rows from under the
    // session anchor, so the server's whole-table `total` can fall below
    // what it was when the session started. The panel takes the count from
    // the server's own after-cursor count for that reason: subtracting a
    // start-of-session snapshot goes negative here, which used to pin the
    // badge at 0 (and the "#N" numbering at zero or below) while records
    // kept rendering underneath it.
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
      // Fewer rows remain table-wide than existed at session start.
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

  it('keeps this session across a tab reload', async () => {
    // A reload is the reflex for "did that just get logged?" — it must not
    // throw the session away. The baseline lives in sessionStorage, so a
    // fresh page load of the same tab resumes from where the session began
    // instead of re-anchoring to the current high-water id (which would
    // hide everything logged so far).
    window.sessionStorage.setItem(
      'cosci-logs-session-baseline',
      JSON.stringify({id: 100}),
    );
    logsApiMock.getAppLogs.mockReset();
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        logRecord(101, {message: 'logged before the reload'}),
        logRecord(102, {message: 'logged after the reload'}),
      ],
      last_id: 102,
      total: 7,
      session_total: 2,
    });

    renderLayout('/');
    fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));

    expect(await screen.findByText(/logged before the reload/)).toBeVisible();
    expect(screen.getByText(/logged after the reload/)).toBeVisible();
    // Numbering continues from the session's start, not from this load.
    expect(screen.getByText('Total 2')).toBeInTheDocument();
    expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(100, 100);
  });
});

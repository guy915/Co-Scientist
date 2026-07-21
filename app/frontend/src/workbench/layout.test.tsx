import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {Run} from '@/api/runs';
import {makeRun} from '@/test_fixtures';
import {AudienceProvider} from './audience_context';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {RunHistoryProvider} from './hooks/run_history_context';
import {Layout} from './layout';
import {ThemeProvider} from './theme_context';

const apiMock = vi.hoisted(() => {
  const listDemoRuns = vi.fn();
  const listRuns = vi.fn();
  const getRunEvents = vi.fn();
  // Mirror the real loadRunHistory so tests keep driving history through the
  // listRuns/listDemoRuns mocks, while reusing the real merge policy.
  const loadRunHistory = vi.fn(async () => {
    const [owned, demo] = await Promise.all([
      listRuns().catch(() => []),
      listDemoRuns().catch(() => []),
    ]);
    const {mergeByIdNewestFirst} = await import('@/lib/merge');
    return mergeByIdNewestFirst(
      [...owned, ...demo] as Run[],
      run => run.id,
      run => run.updated_at,
    );
  });
  return {listDemoRuns, listRuns, getRunEvents, loadRunHistory};
});

const systemApiMock = vi.hoisted(() => ({getSystemStatus: vi.fn()}));

const logsApiMock = vi.hoisted(() => ({
  getAppLogs: vi.fn(),
  postAppLogs: vi.fn(),
  deleteAppLogs: vi.fn(),
}));

// Spread the real module so pure helpers (isActiveStatus, ...) stay real and
// only the network calls are faked, matching chat_workspace_test_helpers.
vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  ...apiMock,
}));

vi.mock('@/api/system', () => systemApiMock);

// Spread the real module so constants (APP_LOGS_CHANGED_EVENT) stay real
// while the network calls are faked.
vi.mock('@/api/logs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/logs')>()),
  ...logsApiMock,
}));

function renderLayout(path = '/') {
  return render(
    <ThemeProvider>
      {/* Declared up front so AudienceGate doesn't open the affiliation
          chooser over the shell these tests are asserting on. */}
      <AudienceProvider initialAudience="general">
        <MemoryRouter initialEntries={[path]}>
          <RunHistoryProvider>
            <Layout>
              <main>Workspace content</main>
            </Layout>
          </RunHistoryProvider>
        </MemoryRouter>
      </AudienceProvider>
    </ThemeProvider>,
  );
}

function runFixture(id: string, goal: string) {
  return {
    ...makeRun({
      id,
      research_goal: goal,
      provider: 'mock',
      created_at: 1,
      updated_at: 2,
      completed_at: 3,
    }),
    summary: {events: 1, hypotheses: 1, evidence: 1, matches: 1, reviews: 1},
  };
}

describe('Layout', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem('cosci-theme', 'dark');
    document.documentElement.dataset.theme = '';
    document.documentElement.classList.remove('dark');
    apiMock.listRuns.mockResolvedValue([]);
    apiMock.listDemoRuns.mockResolvedValue([
      runFixture(
        'demo-ferroptosis',
        'Generate testable hypotheses for ferroptosis in pancreatic cancer cells.',
      ),
    ]);
    apiMock.getRunEvents.mockReset();
    apiMock.getRunEvents.mockResolvedValue([]);
    logsApiMock.getAppLogs.mockReset();
    logsApiMock.getAppLogs.mockResolvedValue({logs: [], last_id: 0, total: 0});
    logsApiMock.postAppLogs.mockReset();
    logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
    logsApiMock.deleteAppLogs.mockReset();
    logsApiMock.deleteAppLogs.mockResolvedValue({deleted: 0});
    // Engine mode by default so the header status chip stays hidden and
    // pre-existing header assertions are unaffected.
    systemApiMock.getSystemStatus.mockReset();
    systemApiMock.getSystemStatus.mockResolvedValue({
      mock_mode: false,
      llm_backend: 'real',
      provider: 'engine',
      model_name: 'test/model',
    });
  });

  it('toggles the Co-Scientist sidebar from the menu button', async () => {
    const {container} = renderLayout();

    // Collapsed icon rail by default, matching the reference product.
    const menu = screen.getByRole('button', {name: 'Menu'});
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(menu).toHaveTextContent('Menu');
    expect(container.querySelector('.ucs-app-shell')).toHaveClass(
      'nav-collapsed',
    );

    fireEvent.click(menu);

    expect(menu).toHaveAttribute('aria-expanded', 'true');
    expect(container.querySelector('.ucs-app-shell')).toHaveClass('nav-open');

    fireEvent.click(menu);

    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(container.querySelector('.ucs-app-shell')).toHaveClass(
      'nav-collapsed',
    );
  });

  it('keeps only Co-Scientist navigation and real chat history', async () => {
    renderLayout();

    expect(screen.queryByRole('button', {name: 'Library'})).toBeNull();
    expect(screen.queryByRole('button', {name: 'Skills'})).toBeNull();
    expect(screen.queryByText('Agents')).toBeNull();
    expect(screen.queryByText('Deep Research')).toBeNull();
    expect(screen.queryByText('NotebookLM')).toBeNull();
    expect(screen.queryByLabelText('Switch to Gemini app')).toBeNull();
    expect(screen.getByRole('button', {name: /Logs 0/i})).toBeInTheDocument();

    expect(await screen.findByText('Chats')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('link', {name: /ferroptosis/i})).toHaveAttribute(
        'href',
        '/runs/demo-ferroptosis/details',
      );
    });

    const newChat = screen.getByRole('button', {name: 'New chat'});
    expect(newChat).toHaveAttribute('data-tooltip', 'New chat');
    expect(newChat).toHaveClass('ucs-tooltip-anchor');
    expect(newChat).toHaveClass('ucs-tooltip-right');

    // The non-functional "Search" nav item was removed.
    expect(screen.queryByRole('button', {name: 'Search'})).toBeNull();

    const chat = screen.getByRole('link', {name: /ferroptosis/i});
    expect(chat).not.toHaveAttribute('title');
    expect(chat.getAttribute('data-tooltip')).toMatch(
      /ferroptosis in pancreatic cancer cells/i,
    );
    expect(chat).toHaveClass('ucs-tooltip-wrap');
  });

  it('shows the generated session title in sidebar chats', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      {
        ...runFixture(
          'run-titled',
          'Generate testable hypotheses for ferroptosis in pancreatic cancer cells.',
        ),
        title: 'Ferroptosis in pancreatic cancer',
      },
    ]);

    renderLayout();

    // The sidebar link renders the model-generated title, not a clause of the
    // raw research goal, matching the recents cards.
    const chat = await screen.findByRole('link', {
      name: 'Ferroptosis in pancreatic cancer',
    });
    expect(chat).toHaveAttribute('href', '/runs/run-titled/details');
    // The full research goal still rides along as the hover tooltip.
    expect(chat.getAttribute('data-tooltip')).toMatch(
      /Generate testable hypotheses for ferroptosis/i,
    );
  });

  it('shows ten sidebar chats before expanding the rest', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue(
      Array.from({length: 12}, (_, index) =>
        runFixture(
          `run-${index + 1}`,
          `Very long sidebar research question ${index + 1}`,
        ),
      ),
    );

    renderLayout();

    expect(
      await screen.findByRole('link', {
        name: /Very long sidebar research question 10/i,
      }),
    ).toHaveAttribute('data-tooltip', 'Very long sidebar research question 10');
    expect(
      screen.queryByRole('link', {
        name: /Very long sidebar research question 11/i,
      }),
    ).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Show more'}));

    expect(
      screen.getByRole('link', {
        name: /Very long sidebar research question 11/i,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Show more'})).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Show less'}));

    expect(
      screen.queryByRole('link', {
        name: /Very long sidebar research question 11/i,
      }),
    ).toBeNull();
    expect(screen.getByRole('button', {name: 'Show more'})).toBeInTheDocument();
  });

  it('opens shell panels from icon buttons and dismisses on outside click', async () => {
    renderLayout();

    fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
    expect(
      screen.getByRole('menuitem', {name: 'Appearance'}),
    ).toBeInTheDocument();
    expect(screen.getByRole('menuitem', {name: 'Model'})).toBeInTheDocument();
    expect(screen.getByRole('menuitem', {name: 'Help'})).toBeInTheDocument();
    // The menu itself has no location line and no theme control; those move
    // into the dialog.
    expect(screen.queryByText(/Dublin/)).toBeNull();
    expect(screen.queryByRole('group', {name: 'Theme'})).toBeNull();
    expect(screen.queryByRole('dialog', {name: 'Settings'})).toBeNull();

    fireEvent.pointerDown(screen.getByText('Workspace content'));
    expect(screen.queryByRole('menuitem', {name: 'Appearance'})).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: /Logs 0/i}));
    expect(screen.getByRole('button', {name: /Logs 0/i})).toHaveAttribute(
      'data-tooltip',
      'Logs',
    );
    expect(screen.getByText('Diagnostic Logs')).toBeInTheDocument();
    expect(screen.queryByText('All runs')).toBeNull();
    expect(screen.getByText('Total 0')).toBeInTheDocument();
    expect(screen.getByText('Errors 0')).toBeInTheDocument();
    expect(screen.getByText('Info 0')).toBeInTheDocument();
    expect(
      screen.getByText('No diagnostic events loaded.'),
    ).toBeInTheDocument();
    const diagnosticActions = document.querySelector('.ucs-diagnostic-actions');
    expect(diagnosticActions).not.toBeNull();
    expect(
      Array.from(diagnosticActions!.querySelectorAll('button')).map(button =>
        button.querySelector('span')?.textContent?.trim(),
      ),
    ).toEqual(['Clear', 'Copy']);

    fireEvent.pointerDown(screen.getByText('Workspace content'));
    expect(screen.queryByText('Diagnostic Logs')).toBeNull();
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

  it('opens the Settings dialog from the menu and switches sections', async () => {
    renderLayout();

    fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
    fireEvent.click(screen.getByRole('menuitem', {name: 'Appearance'}));

    expect(
      await screen.findByRole('dialog', {name: 'Settings'}),
    ).toBeInTheDocument();
    // The menu popover is dismissed once the dialog opens.
    expect(screen.queryByRole('menuitem', {name: 'Appearance'})).toBeNull();

    expect(screen.getByRole('group', {name: 'Theme'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Dark'})).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.click(screen.getByRole('button', {name: 'Light'}));
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(screen.getByRole('button', {name: 'Light'})).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    fireEvent.click(screen.getByRole('button', {name: 'Model'}));
    const input = screen.getByLabelText('DeepSeek API key');
    fireEvent.change(input, {target: {value: 'sk-test-123'}});
    fireEvent.keyDown(input, {key: 'Enter'});
    expect(window.localStorage.getItem('cosci-api-key')).toBe('sk-test-123');
    expect(screen.getByText('Settings saved')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Help'}));
    // The Help section renders project info plus the FAQ accordion rows
    // (native <details>, one per question).
    expect(screen.getByText('What is Co-Scientist?')).toBeInTheDocument();
    expect(screen.getByText('Where does my API key go?')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Close settings'}));
    expect(screen.queryByRole('dialog', {name: 'Settings'})).toBeNull();
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

  it('does not show an overflow menu on run routes', () => {
    renderLayout('/runs/demo-ferroptosis/ideas');

    expect(screen.queryByRole('button', {name: 'More options'})).toBeNull();
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
        {
          id: 3,
          created_at: 1_700_000_000,
          level: 'ERROR',
          levelno: 40,
          logger: 'app.engine_adapter',
          message: 'workflow exploded',
          run_id: null,
          exc_text: null,
        },
        {
          id: 4,
          created_at: 1_700_000_050,
          level: 'INFO',
          levelno: 20,
          logger: 'app.runs',
          message: 'run started',
          run_id: 'run-12345678',
          exc_text: null,
        },
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
      logs: [
        {
          id,
          created_at: 1_700_000_000 + id,
          level: 'INFO',
          levelno: 20,
          logger: 'app.main',
          message: `record ${id}`,
          run_id: null,
          exc_text: null,
        },
      ],
      last_id: id,
      total: id,
    });
    // Let the mount-time loads settle first — including the remount
    // caused by the navigation-log version bump — so both racing
    // requests below belong to the same effect generation (the
    // `disposed` guard must not be what saves us).
    renderLayout();
    await waitFor(() =>
      expect(logsApiMock.getAppLogs.mock.calls.length).toBeGreaterThanOrEqual(
        2,
      ),
    );
    await act(async () => {
      // let the remounted effect finish its initial load
    });

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
        {
          id: 1,
          created_at: 1_700_000_000,
          level: 'INFO',
          levelno: 20,
          logger: 'app.main',
          message: 'a long message that must wrap freely',
          run_id: null,
          exc_text: null,
        },
        {
          id: 2,
          created_at: 1_700_000_001,
          level: 'ERROR',
          levelno: 40,
          logger: 'app.engine_adapter',
          message: 'workflow exploded',
          run_id: null,
          exc_text: 'Traceback: boom',
        },
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
    const record = (id: number) => ({
      id,
      created_at: 1_700_000_000 + id,
      level: 'INFO',
      levelno: 20,
      logger: 'app.main',
      message: `record ${id}`,
      run_id: null,
      exc_text: null,
    });
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [record(1), record(2)],
      last_id: 2,
      total: 2,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
    const list = await screen.findByLabelText('Log events');

    // Simulate a scrollable list with the user scrolled well above the
    // bottom (jsdom does no layout, so the geometry is stubbed).
    Object.defineProperty(list, 'scrollHeight', {
      configurable: true,
      value: 1000,
    });
    Object.defineProperty(list, 'clientHeight', {
      configurable: true,
      value: 100,
    });
    list.scrollTop = 100;
    fireEvent.scroll(list);

    // New records arrive (an in-page event bumps the fetch version).
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [record(1), record(2), record(3)],
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
    const record = (id: number) => ({
      id,
      created_at: 1_700_000_000 + id,
      level: 'INFO',
      levelno: 20,
      logger: 'app.main',
      message: `record ${id}`,
      run_id: null,
      exc_text: null,
    });
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [record(1), record(2)],
      last_id: 2,
      total: 2,
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
    const list = await screen.findByLabelText('Log events');

    Object.defineProperty(list, 'scrollHeight', {
      configurable: true,
      value: 1000,
    });
    Object.defineProperty(list, 'clientHeight', {
      configurable: true,
      value: 100,
    });
    list.scrollTop = 900; // at the bottom: pinned
    fireEvent.scroll(list);

    // The window is at its cap: a new record replaces the oldest, so the
    // entry COUNT stays the same and only the ids advance. Auto-follow
    // must still fire for the pinned reader.
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [record(2), record(3)],
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

  it('refreshes the badge when the api announces a log change', async () => {
    renderLayout();
    await screen.findByRole('button', {name: /Logs 0/i});

    // A client record was persisted somewhere (e.g. a button click was
    // logged): the api layer announces it and the badge updates without
    // the popover ever being opened.
    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        {
          id: 7,
          created_at: 1_700_000_007,
          level: 'INFO',
          levelno: 20,
          logger: 'ui.interaction',
          message: 'click: "Start" (button)',
          run_id: null,
          exc_text: null,
        },
      ],
      last_id: 7,
      total: 7,
    });
    const {APP_LOGS_CHANGED_EVENT} = await import('@/api/logs');
    fireEvent(window, new Event(APP_LOGS_CHANGED_EVENT));

    expect(
      await screen.findByRole('button', {name: /Logs 7/i}),
    ).toBeInTheDocument();
  });

  it('keeps the badge fresh in the background while the popover is closed', async () => {
    vi.useFakeTimers();
    try {
      renderLayout();
      // Flush the initial mount-time loads.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByRole('button', {name: /Logs 0/i})).toBeInTheDocument();

      logsApiMock.getAppLogs.mockResolvedValue({
        logs: [
          {
            id: 9,
            created_at: 1_700_000_009,
            level: 'INFO',
            levelno: 20,
            logger: 'app.main',
            message: 'run finished',
            run_id: null,
            exc_text: null,
          },
        ],
        last_id: 9,
        total: 9,
      });
      // No popover open, no events: only the periodic background poll
      // can pick up the new record.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(screen.getByRole('button', {name: /Logs 9/i})).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows the offline-mode status chip when /status reports the offline backend', async () => {
    systemApiMock.getSystemStatus.mockResolvedValue({
      mock_mode: true,
      llm_backend: 'offline',
      provider: 'engine',
      model_name: 'test/model',
    });

    renderLayout();

    expect(await screen.findByRole('status')).toHaveTextContent('Offline mode');
  });
});

import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {Run} from '@/api/runs';
import {makeRun} from '@/test-fixtures';
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

vi.mock('@/api/logs', () => logsApiMock);

function renderLayout(path = '/') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <RunHistoryProvider>
          <Layout>
            <main>Workspace content</main>
          </Layout>
        </RunHistoryProvider>
      </MemoryRouter>
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
    logsApiMock.getAppLogs.mockResolvedValue({logs: [], last_id: 0});
    logsApiMock.postAppLogs.mockReset();
    logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
    logsApiMock.deleteAppLogs.mockReset();
    logsApiMock.deleteAppLogs.mockResolvedValue({deleted: 0});
    // Engine mode by default so the header status chip stays hidden and
    // pre-existing header assertions are unaffected.
    systemApiMock.getSystemStatus.mockReset();
    systemApiMock.getSystemStatus.mockResolvedValue({
      mock_mode: false,
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

  it('ships in-page diagnostic events to the persisted log', async () => {
    renderLayout();

    fireEvent(
      window,
      new CustomEvent(DIAGNOSTIC_EVENT, {
        detail: {
          stage: 'LIFECYCLE',
          run: 'run-abc',
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
    });
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
    expect(await screen.findByText(/server started/)).toBeInTheDocument();

    logsApiMock.getAppLogs.mockResolvedValue({logs: [], last_id: 1});
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
    logsApiMock.getAppLogs.mockResolvedValue({logs: many, last_id: 60});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {clipboard: {writeText}});
    renderLayout();

    fireEvent.click(await screen.findByRole('button', {name: /Logs 60/i}));
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
    });
    renderLayout('/runs/demo-ferroptosis/ideas');

    fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));

    // Entering a run subpage must not swap the log for a run-scoped view:
    // the panel is the app-wide stream everywhere, numbered by store id.
    expect(await screen.findByText(/server started/)).toBeInTheDocument();
    expect(screen.getByText('#41')).toBeInTheDocument();
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

  it('shows the mock-mode status chip when /status reports mock mode', async () => {
    systemApiMock.getSystemStatus.mockResolvedValue({
      mock_mode: true,
      provider: 'mock',
      model_name: 'test/model',
    });

    renderLayout();

    expect(await screen.findByRole('status')).toHaveTextContent('Mock mode');
  });
});

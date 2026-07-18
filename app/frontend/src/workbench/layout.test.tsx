import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {Run} from '@/api/runs';
import {makeRun} from '@/test-fixtures';
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

// Spread the real module so pure helpers (isActiveStatus, ...) stay real and
// only the network calls are faked, matching chat_workspace_test_helpers.
vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  ...apiMock,
}));

vi.mock('@/api/system', () => systemApiMock);

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
    expect(screen.getByText('Success 0')).toBeInTheDocument();
    expect(screen.getByText('Info 0')).toBeInTheDocument();
    expect(screen.getByText('Runs 0')).toBeInTheDocument();
    expect(screen.queryByText(/Export includes loaded run events/)).toBeNull();
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

    fireEvent(
      window,
      new CustomEvent(DIAGNOSTIC_EVENT, {
        detail: {
          stage: 'LIFECYCLE',
          run: 'Investigate glucose homeostasis',
          level: 'success',
          payload: {event: 'draft_created'},
        },
      }),
    );

    expect(
      await screen.findByRole('button', {name: /Logs 1/i}),
    ).toBeInTheDocument();
    expect(screen.getByText('Total 1')).toBeInTheDocument();
    expect(screen.getByText('Success 1')).toBeInTheDocument();
    expect(screen.getByText('Info 0')).toBeInTheDocument();
    expect(screen.getByText('Runs 1')).toBeInTheDocument();
    expect(screen.getByText(/"event": "draft_created"/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));
    expect(screen.getByRole('button', {name: /Logs 0/i})).toBeInTheDocument();
    expect(
      screen.getByText('No diagnostic events loaded.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/"event": "draft_created"/)).toBeNull();

    fireEvent.pointerDown(screen.getByText('Workspace content'));
    expect(screen.queryByText('Diagnostic Logs')).toBeNull();
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

  it('loads the persisted run timeline into the diagnostics popover', async () => {
    apiMock.getRunEvents.mockResolvedValue([
      {
        seq: 1,
        type: 'lifecycle',
        payload: {event: 'created'},
        created_at: 1_700_000_000,
      },
      {
        seq: 2,
        type: 'status',
        payload: {status: 'failed', error: 'boom'},
        created_at: 1_700_000_100,
      },
    ]);
    renderLayout('/runs/demo-ferroptosis/ideas');

    fireEvent.click(screen.getByRole('button', {name: /Logs 0/i}));

    // The popover fetches the active run's persisted event log on open.
    await waitFor(() =>
      expect(apiMock.getRunEvents).toHaveBeenCalledWith('demo-ferroptosis'),
    );
    expect(await screen.findByText('lifecycle:')).toBeInTheDocument();
    expect(screen.getByText(/"event": "created"/)).toBeInTheDocument();
    // Terminal failures read as errors in the summary chips.
    expect(screen.getByText('Total 2')).toBeInTheDocument();
    expect(screen.getByText('Errors 1')).toBeInTheDocument();
    expect(
      await screen.findByRole('button', {name: /Logs 2/i}),
    ).toBeInTheDocument();

    // Clear drops only session entries; the persisted timeline remains.
    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));
    expect(screen.getByText(/"event": "created"/)).toBeInTheDocument();
  });

  it('keeps the persisted timeline out of the popover on home routes', () => {
    renderLayout('/');

    fireEvent.click(screen.getByRole('button', {name: /Logs 0/i}));

    expect(apiMock.getRunEvents).not.toHaveBeenCalled();
    expect(
      screen.getByText('No diagnostic events loaded.'),
    ).toBeInTheDocument();
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

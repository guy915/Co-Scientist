import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  apiMock,
  installLayoutMocks,
  logsApiMock,
  renderLayout,
  runFixture,
  systemApiMock,
} from './layout_test_utils';

/** Renders the layout with twelve real runs feeding the sidebar chat list. */
function renderTwelveSidebarChats() {
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
}

describe('Layout', () => {
  beforeEach(() => {
    installLayoutMocks();
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
    renderTwelveSidebarChats();

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

  it('opens the settings menu and dismisses on outside click', async () => {
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
  });

  it('opens the logs popover and dismisses on outside click', async () => {
    renderLayout();

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

  it('does not show an overflow menu on run routes', () => {
    renderLayout('/runs/demo-ferroptosis/ideas');

    expect(screen.queryByRole('button', {name: 'More options'})).toBeNull();
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

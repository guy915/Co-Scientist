import {act, fireEvent, screen, render, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi, afterEach, describe} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
  apiMock,
  chatFixture,
} from './layout_test_support';
import {ShellPopover} from './layout_primitives';

describe('layout logs', () => {
  beforeEach(() => {
    installLayoutMocks();
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
    expect(screen.getByText('Warnings 0')).toBeInTheDocument();
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
    ).toEqual(['Clear', 'Copy', 'Report']);
    // Report is present but inert until the server can send mail, and says so
    // rather than leaving the scientist to discover it by clicking.
    const report = screen.getByRole('button', {name: /Report/});
    expect(report).toBeDisabled();
    expect(report).toHaveAttribute(
      'data-tooltip',
      'Email delivery is not configured on this server',
    );

    fireEvent.pointerDown(screen.getByText('Workspace content'));
    expect(screen.queryByText('Diagnostic Logs')).toBeNull();
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
      session_total: 7,
    });
    const {APP_LOGS_CHANGED_EVENT} = await import('@/api/logs');
    fireEvent(window, new Event(APP_LOGS_CHANGED_EVENT));

    expect(
      await screen.findByRole('button', {name: /Logs 7/i}),
    ).toBeInTheDocument();
  });

  it('keeps the badge fresh while the popover is closed', async () => {
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
        session_total: 9,
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
});

describe('layout no shortcuts', () => {
  // The app deliberately binds no keyboard shortcuts. It used to carry two --
  // "g n" for home and ArrowLeft/ArrowRight to cycle a run's report tabs --
  // bound on `document` regardless of focus, which is exactly what makes them
  // hard to notice coming back: nothing on screen changes when one is added,
  // and the only symptom is a keypress doing something unasked for. Spying on
  // the registration is the one check that fails the moment a document-level
  // binding returns.
  //
  // Dialog keys are a different thing and are not covered here: Escape closing
  // an open dialog and Tab staying inside it are that dialog's own semantics
  // (useEscapeKey, useFocusTrap in dom.ts), they register only while it is open, and
  // removing them would be an accessibility regression rather than honoring
  // this rule.
  let addEventListener: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    installLayoutMocks();
    addEventListener = vi.spyOn(document, 'addEventListener');
  });

  afterEach(() => {
    addEventListener.mockRestore();
  });

  // The keydown events the removed shortcuts listened for, so a reintroduction
  // under a different key name still has to pass the registration check above.
  function keydownRegistrations(): unknown[] {
    return addEventListener.mock.calls.filter(
      ([type]: [string, ...unknown[]]) => type === 'keydown',
    );
  }

  it('registers no document keydown handler on the shell', async () => {
    renderLayout('/');
    expect(await screen.findByText('Workspace content')).toBeInTheDocument();

    expect(keydownRegistrations()).toEqual([]);
  });

  it('registers no document keydown handler on a run route', async () => {
    renderLayout('/runs/run-1/details');
    expect(await screen.findByText('Workspace content')).toBeInTheDocument();

    expect(keydownRegistrations()).toEqual([]);
  });
});

describe('layout primitives', () => {
  // O4: the shell's shared popover shell backs every interactive header/rail
  // panel (Settings menu, Logs) -- none of them are status output, so the
  // container must never carry an implicit `role="status"` live region.

  it('never renders as a status live region', () => {
    render(<ShellPopover className="test-popover">content</ShellPopover>);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('renders a plain, unlabelled container when the caller names no role', () => {
    render(<ShellPopover className="test-popover">content</ShellPopover>);
    const popover = screen.getByText('content').parentElement;
    expect(popover).not.toHaveAttribute('role');
    expect(popover).not.toHaveAttribute('aria-label');
  });

  it('carries a labelled group role when the caller names one', () => {
    render(
      <ShellPopover className="test-popover" role="group" ariaLabel="Logs">
        content
      </ShellPopover>,
    );
    expect(screen.getByRole('group', {name: 'Logs'})).toBeInTheDocument();
  });
});

describe('layout settings', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('opens the settings menu and dismisses on outside click', async () => {
    renderLayout();

    fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
    expect(
      screen.getByRole('menuitem', {name: 'Appearance'}),
    ).toBeInTheDocument();
    expect(screen.getByRole('menuitem', {name: 'Model'})).toBeInTheDocument();
    // Help is gone: its FAQ lives on the landing page under the chat home.
    expect(screen.queryByRole('menuitem', {name: 'Help'})).toBeNull();
    // The menu itself has no location line and no theme control; those move
    // into the dialog.
    expect(screen.queryByText(/Dublin/)).toBeNull();
    expect(screen.queryByRole('group', {name: 'Theme'})).toBeNull();
    expect(screen.queryByRole('dialog', {name: 'Settings'})).toBeNull();

    fireEvent.pointerDown(screen.getByText('Workspace content'));
    expect(screen.queryByRole('menuitem', {name: 'Appearance'})).toBeNull();
  });

  it('opens the Settings dialog and switches sections', async () => {
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
    // Saving says nothing: the field holds the value it just stored, and a
    // toast repeating that only covered the page it was confirming.
    expect(screen.queryByText('Settings saved')).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Close settings'}));
    expect(screen.queryByRole('dialog', {name: 'Settings'})).toBeNull();
  });

  it('persists the BYOK provider choice in the Model section', async () => {
    renderLayout();

    fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
    fireEvent.click(screen.getByRole('menuitem', {name: 'Model'}));
    await screen.findByRole('dialog', {name: 'Settings'});

    // The key label follows the chosen provider; deepseek is the default.
    expect(screen.getByLabelText('DeepSeek API key')).toBeInTheDocument();

    // The chooser is our own menu, not a native select: nothing is in the DOM
    // to pick from until the trigger opens it.
    const trigger = screen.getByRole('button', {name: 'Provider'});
    expect(screen.queryByRole('menuitemradio', {name: 'OpenAI'})).toBeNull();
    fireEvent.click(trigger);

    // Azure is deliberately not offered (see BYOK_PROVIDERS).
    expect(screen.queryByRole('menuitemradio', {name: 'Azure'})).toBeNull();
    expect(
      screen.getByRole('menuitemradio', {name: 'DeepSeek'}),
    ).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(screen.getByRole('menuitemradio', {name: 'OpenAI'}));
    expect(window.localStorage.getItem('cosci-api-provider')).toBe('openai');
    expect(screen.getByLabelText('OpenAI API key')).toBeInTheDocument();
    expect(screen.queryByText('Settings saved')).toBeNull();
    // Choosing closes the menu.
    expect(screen.queryByRole('menuitemradio', {name: 'OpenAI'})).toBeNull();
  });

  it("links to every provider's own key page", async () => {
    renderLayout();

    fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
    fireEvent.click(screen.getByRole('menuitem', {name: 'Model'}));
    await screen.findByRole('dialog', {name: 'Settings'});

    // The default provider's link, and the link following a change of
    // provider: a key page is only useful for the provider being keyed.
    expect(
      screen.getByRole('link', {name: /Get a DeepSeek API key/}),
    ).toHaveAttribute('href', 'https://platform.deepseek.com/api_keys');

    fireEvent.click(screen.getByRole('button', {name: 'Provider'}));
    fireEvent.click(screen.getByRole('menuitemradio', {name: 'Anthropic'}));
    expect(
      screen.getByRole('link', {name: /Get an Anthropic API key/}),
    ).toHaveAttribute('href', 'https://platform.claude.com/settings/keys');

    // The line about what the server does with the key is gone.
    expect(screen.queryByText(/stores it encrypted/)).toBeNull();
  });

  it('closes the provider menu on Escape without closing Settings', async () => {
    renderLayout();

    fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
    fireEvent.click(screen.getByRole('menuitem', {name: 'Model'}));
    const dialog = await screen.findByRole('dialog', {name: 'Settings'});

    fireEvent.click(screen.getByRole('button', {name: 'Provider'}));
    const option = screen.getByRole('menuitemradio', {name: 'OpenAI'});
    fireEvent.keyDown(option, {key: 'Escape'});

    expect(screen.queryByRole('menuitemradio', {name: 'OpenAI'})).toBeNull();
    expect(dialog).toBeInTheDocument();
  });
});

describe('layout sidebar', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  /** Renders the layout with twelve real chats feeding the sidebar list. */
  function renderTwelveSidebarChats() {
    apiMock.listInterviews.mockResolvedValue(
      Array.from({length: 12}, (_, index) =>
        chatFixture(
          `chat-${index + 1}`,
          `Very long sidebar research question ${index + 1}`,
        ),
      ),
    );
    renderLayout();
  }

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
    // This chat never started a run, so its row opens the conversation.
    await waitFor(() => {
      expect(screen.getByRole('link', {name: /ferroptosis/i})).toHaveAttribute(
        'href',
        '/chats/chat-ferroptosis',
      );
    });

    // A link, not a button: Cmd/middle-clicking it opens a fresh workspace in
    // a new tab like every other navigation in the rail.
    const newChat = screen.getByRole('link', {name: 'New chat'});
    expect(newChat).toHaveAttribute('href', '/');
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
    apiMock.listInterviews.mockResolvedValue([
      chatFixture(
        'chat-titled',
        'Generate testable hypotheses for ferroptosis in pancreatic cancer ' +
          'cells.',
        {title: 'Ferroptosis in pancreatic cancer'},
      ),
    ]);

    renderLayout();

    // The sidebar link renders the model-generated title, not a clause of the
    // raw research goal, matching the recents cards.
    const chat = await screen.findByRole('link', {
      name: 'Ferroptosis in pancreatic cancer',
    });
    expect(chat).toHaveAttribute('href', '/chats/chat-titled');
    // The full research goal still rides along as the hover tooltip.
    expect(chat.getAttribute('data-tooltip')).toMatch(
      /Generate testable hypotheses for ferroptosis/i,
    );
  });

  it('opens a started session at its run, not back at the chat', async () => {
    apiMock.listInterviews.mockResolvedValue([
      chatFixture('chat-running', 'Map senolytic clearance in aged tissue.', {
        title: 'Senolytic clearance',
        run_id: 'run-senolytic',
        status: 'completed',
      }),
      chatFixture('chat-draft', 'Explore ferroptosis in pancreatic cancer.', {
        title: 'Ferroptosis draft',
      }),
    ]);

    renderLayout();

    // A session that started a run has moved past its conversation, so the
    // row goes to the run — whose own page picks the live progress view or
    // the report from the run's status. A session that never started one
    // still opens the transcript.
    expect(
      await screen.findByRole('link', {name: 'Senolytic clearance'}),
    ).toHaveAttribute('href', '/runs/run-senolytic/details');
    expect(
      screen.getByRole('link', {name: 'Ferroptosis draft'}),
    ).toHaveAttribute('href', '/chats/chat-draft');
  });

  it('shows the chats that fit before expanding the rest', async () => {
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
});

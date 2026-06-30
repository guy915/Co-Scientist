import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {Layout} from './layout';
import {ThemeProvider} from './theme_context';

const apiMock = vi.hoisted(() => ({
  listDemoRuns: vi.fn(),
  listRuns: vi.fn(),
}));

vi.mock('@/api/runs', () => apiMock);

function renderLayout(path = '/') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Layout>
          <main>Workspace content</main>
        </Layout>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function runFixture(id: string, goal: string) {
  return {
    id,
    research_goal: goal,
    profile: 'standard',
    status: 'completed',
    provider: 'mock',
    config: {},
    created_at: 1,
    updated_at: 2,
    completed_at: 3,
    error: null,
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
  });

  it('toggles the Co-Scientist sidebar from the menu button', async () => {
    const {container} = renderLayout();

    const menu = screen.getByRole('button', {name: 'Menu'});
    expect(menu).toHaveAttribute('aria-expanded', 'true');
    expect(menu).toHaveTextContent('Menu');
    expect(container.querySelector('.google-app-shell')).toHaveClass(
      'nav-open',
    );

    fireEvent.click(menu);

    expect(menu).toHaveAttribute('aria-expanded', 'false');
    expect(container.querySelector('.google-app-shell')).toHaveClass(
      'nav-collapsed',
    );

    fireEvent.click(menu);

    expect(menu).toHaveAttribute('aria-expanded', 'true');
    expect(container.querySelector('.google-app-shell')).toHaveClass(
      'nav-open',
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
    expect(screen.getByRole('button', {name: /Logs 23/i})).toBeInTheDocument();

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

    const search = screen.getByRole('button', {name: 'Search'});
    expect(search).toHaveAttribute('data-tooltip', 'Search');
    expect(search).toHaveClass('ucs-tooltip-anchor');
    expect(search).toHaveClass('ucs-tooltip-right');

    const chat = screen.getByRole('link', {name: /ferroptosis/i});
    expect(chat).not.toHaveAttribute('title');
    expect(chat.getAttribute('data-tooltip')).toMatch(
      /ferroptosis in pancreatic cancer cells/i,
    );
    expect(chat).toHaveClass('ucs-tooltip-wrap');
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

  it('opens shell panels from icon buttons and dismisses on outside click', () => {
    renderLayout();

    fireEvent.click(screen.getByRole('button', {name: 'Settings'}));
    expect(screen.getByText('Appearance')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Personalization'})).toBeNull();
    expect(screen.queryByText(/Delft/)).toBeNull();
    expect(screen.getByRole('button', {name: 'Help'})).toBeInTheDocument();
    expect(screen.queryByRole('dialog', {name: 'Settings'})).toBeNull();
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

    fireEvent.pointerDown(screen.getByText('Workspace content'));
    expect(screen.queryByText('Appearance')).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: /Logs 23/i}));
    expect(screen.getByText('Diagnostic Logs')).toBeInTheDocument();
    expect(screen.getByText('All runs')).toBeInTheDocument();
    expect(screen.getByText('Total 23')).toBeInTheDocument();
    expect(
      screen.getByText(/Export includes loaded run events/),
    ).toBeInTheDocument();
    expect(screen.getByText(/"event": "created"/)).toBeInTheDocument();
    const diagnosticActions = document.querySelector('.ucs-diagnostic-actions');
    expect(diagnosticActions).not.toBeNull();
    expect(
      Array.from(diagnosticActions!.querySelectorAll('button')).map(button =>
        button.querySelector('span')?.textContent?.trim(),
      ),
    ).toEqual(['Refresh', 'Clear', 'Copy']);

    fireEvent.click(screen.getByRole('button', {name: 'Clear'}));
    expect(screen.getByRole('button', {name: /Logs 0/i})).toBeInTheDocument();
    expect(
      screen.getByText('No diagnostic events loaded.'),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Refresh'}));
    expect(screen.getByRole('button', {name: /Logs 23/i})).toBeInTheDocument();
    expect(screen.getByText(/"event": "created"/)).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByText('Workspace content'));
    expect(screen.queryByText('Diagnostic Logs')).toBeNull();
  });

  it('does not show an overflow menu on run routes', () => {
    renderLayout('/runs/demo-ferroptosis/ideas');

    expect(screen.queryByRole('button', {name: 'More options'})).toBeNull();
  });
});

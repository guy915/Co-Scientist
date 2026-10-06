import {act, fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it, vi, describe} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
  apiMock,
  chatFixture,
} from './layout_test_support';

describe('layout logs', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('keeps the badge fresh while the popover is closed', async () => {
    vi.useFakeTimers();
    try {
      renderLayout();
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
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(screen.getByRole('button', {name: /Logs 9/i})).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('layout sidebar', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

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

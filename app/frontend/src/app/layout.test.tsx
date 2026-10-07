import {fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it, describe} from 'vitest';
import {
  installLayoutMocks,
  renderLayout,
  apiMock,
  chatFixture,
} from './layout_test_support';

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

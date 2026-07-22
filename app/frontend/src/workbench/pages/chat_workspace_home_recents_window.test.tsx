import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  apiMock,
  installChatWorkspaceMocks,
  minimalRun,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

/**
 * Seeds six completed recent runs so the home stage has more cards than the
 * initial four-card window reveals.
 */
function seedSixRecentRuns() {
  apiMock.listDemoRuns.mockResolvedValue([]);
  apiMock.getHypotheses.mockResolvedValue([]);
  apiMock.listRuns.mockResolvedValue(
    Array.from({length: 6}, (_, index) =>
      minimalRun({
        id: `run-${index + 1}`,
        research_goal: `Recent research question ${index + 1}`,
        created_at: index + 1,
        updated_at: index + 1,
        completed_at: index + 2,
      }),
    ),
  );
}

it('shows four recent cards before revealing the rest', async () => {
  seedSixRecentRuns();

  renderWorkspace();

  expect(
    await screen.findAllByText('Recent research question 6'),
  ).not.toHaveLength(0);
  await waitFor(() => {
    expect(screen.getAllByText('Top score: 1200')).not.toHaveLength(0);
  });
  expect(screen.getAllByText('Recent research question 3')).not.toHaveLength(0);
  expect(screen.queryByText('Recent research question 2')).toBeNull();

  fireEvent.click(screen.getByRole('button', {name: 'Show more'}));

  expect(screen.getAllByText('Recent research question 2')).not.toHaveLength(0);
  expect(screen.getAllByText('Recent research question 1')).not.toHaveLength(0);
  expect(screen.queryByRole('button', {name: 'Show more'})).toBeNull();

  fireEvent.click(screen.getByRole('button', {name: 'Show less'}));

  expect(screen.queryByText('Recent research question 2')).toBeNull();
  expect(screen.getByRole('button', {name: 'Show more'})).toBeInTheDocument();
});

import {screen} from '@testing-library/react';
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

it('uses the run-list top_elo for completed home-card top scores', async () => {
  apiMock.listDemoRuns.mockResolvedValue([]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({
      id: 'run-scored',
      research_goal: 'Rank host-pathogen target hypotheses.',
      top_elo: 1324,
    }),
  ]);

  renderWorkspace();

  expect(await screen.findByText('Top score: 1324')).toBeInTheDocument();
  expect(screen.queryByText('Top score: 1240')).toBeNull();
});

it('renders the run’s real top hypotheses on a completed card', async () => {
  apiMock.listDemoRuns.mockResolvedValue([]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({
      id: 'run-real-titles',
      research_goal: 'Rank host-pathogen target hypotheses.',
      top_hypotheses: [
        'Metabolic refuge disruption hypothesis',
        'Biofilm redox-state vulnerability hypothesis',
      ],
    }),
  ]);

  renderWorkspace();

  expect(
    await screen.findByText('Metabolic refuge disruption hypothesis'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('Biofilm redox-state vulnerability hypothesis'),
  ).toBeInTheDocument();
});

it('omits the winner list for a run that produced no hypotheses', async () => {
  apiMock.listDemoRuns.mockResolvedValue([]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({
      id: 'run-no-hyps',
      research_goal: 'A run that failed before generating anything.',
      status: 'failed',
      top_hypotheses: [],
    }),
  ]);

  const {container} = renderWorkspace();

  // The goal text appears in both the card title and description.
  await screen.findAllByText(/failed before generating anything/i);
  expect(container.querySelector('.reference-winner-list')).toBeNull();
});

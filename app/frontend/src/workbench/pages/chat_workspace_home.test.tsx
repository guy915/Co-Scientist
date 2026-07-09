import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {
  apiMock,
  installChatWorkspaceMocks,
  minimalRun,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

describe('ChatWorkspace home stage', () => {
  it('opens on the reference-style Co-Scientist home screen', async () => {
    renderWorkspace();

    expect(
      screen.getByRole('heading', {
        name: 'What breakthrough should we make today?',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('Recents')).toBeInTheDocument();
    expect(screen.getByText('Frame the research goal')).toBeInTheDocument();
    expect(screen.getByText('Generate hypotheses')).toBeInTheDocument();
    expect(
      screen.getByText('Pressure-test the best ideas'),
    ).toBeInTheDocument();
    expect(screen.queryByText('AI Co-Scientist')).toBeNull();
    expect(
      screen.getByText('Start a new research goal to begin'),
    ).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(
      await screen.findByText(/ferroptosis in pancreatic cancer cells/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {
        name: /ferroptosis in pancreatic cancer cells/i,
      }),
    ).toHaveAttribute('href', '/runs/demo-ferroptosis/details');
  });

  it('shows four recent cards before revealing the rest', async () => {
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

    renderWorkspace();

    expect(
      await screen.findAllByText('Recent research question 6'),
    ).not.toHaveLength(0);
    await waitFor(() => {
      expect(screen.getAllByText('Top score: 1200')).not.toHaveLength(0);
    });
    expect(screen.getAllByText('Recent research question 3')).not.toHaveLength(
      0,
    );
    expect(screen.queryByText('Recent research question 2')).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Show more'}));

    expect(screen.getAllByText('Recent research question 2')).not.toHaveLength(
      0,
    );
    expect(screen.getAllByText('Recent research question 1')).not.toHaveLength(
      0,
    );
    expect(screen.queryByRole('button', {name: 'Show more'})).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Show less'}));

    expect(screen.queryByText('Recent research question 2')).toBeNull();
    expect(screen.getByRole('button', {name: 'Show more'})).toBeInTheDocument();
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

  it('shows active recents with the run step flow', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-active',
        research_goal: 'Investigate synaptic pruning therapies.',
        status: 'running',
        completed_at: null,
        summary: {
          events: 9,
          hypotheses: 3,
          evidence: 0,
          matches: 1,
          reviews: 2,
        },
        updated_at: 20,
      }),
    ]);

    renderWorkspace();

    expect(await screen.findByText(/Step \d of 4/)).toBeInTheDocument();
    expect(screen.getByText('Exploring focus areas')).toBeInTheDocument();
    expect(screen.getByText('Generating hypotheses')).toBeInTheDocument();
    expect(screen.getByText('Reviewing hypotheses')).toBeInTheDocument();
    expect(screen.getByText('Playing tournament')).toBeInTheDocument();
  });

  it('shows the reference empty recents placeholder', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([]);

    const {container} = renderWorkspace();

    expect(
      await screen.findByText('You have not started any sessions yet.'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('.reference-recents-empty-icon'),
    ).not.toBeNull();
    expect(container.querySelector('.reference-assistant-dot')).toBeNull();
  });
});

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
      await screen.findByText(/ferroptosis in pancreatic cancer cells/i, {
        selector: '.reference-recent-description',
      }),
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

  it('shows active recents with the run step flow on the real phase', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-active',
        research_goal: 'Investigate synaptic pruning therapies.',
        status: 'running',
        completed_at: null,
        // The shape a real engine run reports: it leases durable tasks and
        // emits no stage events, and its task budget is never determinate.
        latest_stage: null,
        execution_progress: {
          determinate: false,
          completed_tasks: 3,
          total_tasks: 5,
          fraction: null,
          active_task: 'engine.fanout.reflection.item',
          queued_tasks: 1,
        },
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

    // Reviewing hypotheses is the third of the four phases, so two are behind
    // the run: it reports the two it has finished, not a share of the work.
    expect(await screen.findByText('In Progress : 50%')).toBeInTheDocument();
    expect(screen.getByText('Exploring focus areas')).toBeInTheDocument();
    expect(screen.getByText('Generating hypotheses')).toBeInTheDocument();
    expect(screen.getByText('Reviewing hypotheses')).toBeInTheDocument();
    // The run has not reached the tournament, so that phase is not shown yet.
    expect(screen.queryByText('Playing tournament')).toBeNull();

    const checked = [...document.querySelectorAll('.reference-run-step')]
      .filter(step => step.querySelector('.reference-run-step-done'))
      .map(
        step => step.querySelector('.reference-run-step-label')?.textContent,
      );
    expect(checked).toEqual(['Exploring focus areas', 'Generating hypotheses']);
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

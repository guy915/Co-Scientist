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

it('shows active recents with the run step flow', async () => {
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

  // Reviewing hypotheses is the third of the four phases, so the run lists
  // the three it has entered and not the tournament it has not reached.
  expect(await screen.findByText('In Progress')).toBeInTheDocument();
  expect(screen.getByText('Exploring focus areas')).toBeInTheDocument();
  expect(screen.getByText('Generating hypotheses')).toBeInTheDocument();
  expect(screen.getByText('Reviewing hypotheses')).toBeInTheDocument();
  expect(screen.queryByText('Playing tournament')).toBeNull();
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

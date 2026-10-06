import {stubViewport} from '@/browser_test_support';
import {resetRunDetailMocks, setStream} from './run_detail_api_test_support';
import * as runsApi from '@/api/runs';
import {screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {makeRun, renderAt} from './run_detail_test_support';

// The mobile titlebar is the detail view's only route back to the ranked list.
it('returns to the ranked ideas list when an idea is open', async () => {
  stubViewport(true);
  renderAt('/runs/run-1/ideas?idea=h-1');

  expect(
    await screen.findByRole('link', {name: 'Back to ranked ideas'}),
  ).toHaveAttribute('href', '/runs/run-1/ideas');
});

// Desktop keeps the list visible; Back must leave the run rather than clear
// selection.

it('shows live metrics and activity instead of report controls', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'running',
    created_at: Date.now() / 1000 - 5,
    execution_progress: {
      determinate: false,
      completed_tasks: 4,
      total_tasks: 9,
      fraction: null,
      active_task: 'engine.node.generate',
      queued_tasks: 3,
    },
  });
  setStream([{seq: 1, type: 'scientific_task', payload: {task: 'generate'}}]);

  renderAt('/runs/run-1/specifications');

  expect(await screen.findByText('Research in progress')).toBeInTheDocument();
  expect(screen.getByText('Time elapsed')).toBeInTheDocument();
  expect(screen.getByText('< 1 minute')).toBeInTheDocument();
  expect(screen.getByText('Sources Analyzed')).toBeInTheDocument();
  expect(screen.getByText('Ideas explored')).toBeInTheDocument();
  expect(screen.getByText('Engine Node Generate')).toBeInTheDocument();
  const activityLog = screen.getByRole('region', {name: 'Activity log'});
  expect(activityLog).toHaveTextContent('Live activity');
  expect(activityLog).toHaveTextContent('Generating hypotheses');
  expect(screen.queryByText('Open in NotebookLM')).toBeNull();
  expect(screen.queryByRole('link', {name: 'Download'})).toBeNull();
  expect(screen.queryByText('Run Specifications')).toBeNull();
});

it.each([
  ['failed', 'Run failed', 'engine.node.generate exhausted its retry budget'],
  ['blocked', 'Run blocked', 'Safety screen held the run for adjudication'],
  ['cancelled', 'Run cancelled', undefined],
] as const)(
  'renders the %s end state with its recorded error, not report tabs',
  async (status, heading, error) => {
    vi.mocked(runsApi.getRun).mockResolvedValue({
      ...makeRun('Study pathway X'),
      status,
      error: error ?? null,
    });

    renderAt('/runs/run-1/details');

    expect(await screen.findByText(heading)).toBeInTheDocument();
    if (error) expect(screen.getByText(error)).toBeInTheDocument();
    expect(screen.queryByRole('link', {name: 'Goal Details'})).toBeNull();
    expect(screen.queryByRole('link', {name: 'All Ideas'})).toBeNull();
    expect(screen.queryByText('Run Specifications')).toBeNull();
  },
);

// jsdom cannot measure overlap; keep safety notices inside the scrolling body,
// not extra grid tracks.
it('shows the awaiting-decision notice on every tab, nested in the scroll region', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'paused',
    awaiting_decision_count: 2,
  });

  renderAt('/runs/run-1/ideas');

  const notice = await screen.findByRole('note');
  expect(notice).toHaveTextContent(/waiting on 2 safety decisions/);
  const page = document.querySelector('.cosci-report-page');
  const scrollRegion = document.querySelector('.cosci-report-scroll');
  expect(Array.from(page?.children ?? [])).not.toContain(notice);
  expect(scrollRegion).toContainElement(notice);
});

// Local overflow clipping would defeat the ancestor's horizontal-scroll policy.

beforeEach(() => {
  resetRunDetailMocks();
  vi.mocked(runsApi.listInterviews).mockResolvedValue([]);
  vi.unstubAllGlobals();
});

it('omits the notice for a paused run with nothing left to review', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'paused',
    awaiting_decision_count: 0,
  });

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByRole('note')).toBeNull();
});

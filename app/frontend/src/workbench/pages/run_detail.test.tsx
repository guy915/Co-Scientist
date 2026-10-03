import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {makeRun, renderAt} from './run_detail_test_support';

const streamMock = vi.hoisted(() => ({
  state: {events: [] as {seq: number; type: string; payload: object}[]},
}));
vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({events: streamMock.state.events, terminal: false}),
}));

vi.mock('@/workbench/hooks/timers', async importOriginal => {
  const actual =
    await importOriginal<typeof import('@/workbench/hooks/timers')>();
  const timer = {schedule: (run: () => void) => run(), cancel: () => {}};
  return {...actual, useResetTimer: () => timer};
});

function setStream(events: {seq: number; type: string; payload: object}[]) {
  streamMock.state = {events};
}

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    getRun: vi.fn(),
    getSupervisorPlan: vi.fn().mockResolvedValue({plan: null, allocations: []}),
    getHypotheses: vi.fn().mockResolvedValue([]),
    getEvidence: vi.fn().mockResolvedValue([]),
    getMatches: vi.fn().mockResolvedValue([]),
    getReviews: vi.fn().mockResolvedValue([]),
    getClaimEvidence: vi.fn().mockResolvedValue([]),
    getSafety: vi.fn().mockResolvedValue([]),
    adjudicateSafety: vi.fn().mockResolvedValue({
      decision_id: 1,
      resolution: 'approved',
    }),
    getCitations: vi.fn().mockResolvedValue([]),
    listInterviews: vi.fn().mockResolvedValue([]),
    getReport: vi.fn().mockResolvedValue(null),
    sendRunSteering: vi
      .fn()
      .mockResolvedValue({id: 'message-1', status: 'queued'}),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  // Viewport stubs must not leak into another test.
  vi.unstubAllGlobals();
  setStream([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  vi.mocked(runsApi.getSupervisorPlan).mockResolvedValue({
    plan: null,
    allocations: [],
  });
  // Reset collection overrides between tests.
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([]);
  vi.mocked(runsApi.getMatches).mockResolvedValue([]);
  vi.mocked(runsApi.getReport).mockResolvedValue(null);
  vi.mocked(runsApi.getSafety).mockResolvedValue([]);
  vi.mocked(runsApi.listInterviews).mockResolvedValue([]);
});

it('leaves the run for the workspace even when a chat started it', async () => {
  vi.mocked(runsApi.listInterviews).mockResolvedValue([
    {
      id: 'chat-7',
      title: 'Pathway X',
      challenge: 'Study pathway X',
      status: 'completed',
      run_id: 'run-1',
      created_at: 1,
      updated_at: 2,
    },
  ]);

  renderAt('/runs/run-1/details');

  expect(await screen.findByRole('link', {name: 'Back'})).toHaveAttribute(
    'href',
    '/',
  );
});

it('falls back to the workspace when no conversation started the run', async () => {
  renderAt('/runs/run-1/details');

  expect(await screen.findByRole('link', {name: 'Back'})).toHaveAttribute(
    'href',
    '/',
  );
});

// jsdom lacks matchMedia; unstubbed tests silently exercise desktop behavior.
function stubViewport(mobile: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: mobile,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );
}

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
it('still leaves the run with an idea open on desktop', async () => {
  stubViewport(false);
  renderAt('/runs/run-1/ideas?idea=h-1');

  expect(await screen.findByRole('link', {name: 'Back'})).toHaveAttribute(
    'href',
    '/',
  );
});

it('still leaves the run from the ideas tab when no idea is open', async () => {
  renderAt('/runs/run-1/ideas');

  expect(await screen.findByRole('link', {name: 'Back'})).toHaveAttribute(
    'href',
    '/',
  );
});

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

it('shows the persisted allocation ledger after loading a completed run', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'completed',
  });
  vi.mocked(runsApi.getSupervisorPlan).mockResolvedValue({
    plan: {
      run_id: 'run-1',
      plan: {},
      orchestrator_state: {},
      decision_provenance: 'model',
      termination_reason: 'satisfied_completion',
      created_at: 1_790_000_000,
      updated_at: 1_790_000_001,
    },
    allocations: [
      {
        id: 4,
        run_id: 'run-1',
        seq: 0,
        iteration: 1,
        task_type: 'generate',
        status: 'queued',
        reason: 'The pool has no generated hypotheses.',
        planner_reason: 'Start with one focused generation pass.',
        priority: 80,
        termination_reason: null,
        created_at: 1_790_000_000,
      },
    ],
  });

  renderAt('/runs/run-1/details');

  const summary = await screen.findByText('Supervisor allocation ledger');
  await userEvent.click(summary);
  expect(
    screen.getByText('The pool has no generated hypotheses.'),
  ).toBeInTheDocument();
  expect(screen.getByText('Model-stated rationale')).toBeInTheDocument();
  expect(
    screen.getByText('Most recent decision source: model'),
  ).toBeInTheDocument();
  expect(runsApi.getSupervisorPlan).toHaveBeenCalledWith('run-1');
});

it('keeps saved allocations available on a failed run', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'failed',
    error: 'The run stopped before report synthesis.',
  });
  vi.mocked(runsApi.getSupervisorPlan).mockResolvedValue({
    plan: null,
    allocations: [
      {
        id: 8,
        run_id: 'run-1',
        seq: 0,
        iteration: 1,
        task_type: 'generate',
        status: 'completed',
        reason: 'The first allocation committed before the failure.',
        planner_reason: null,
        priority: 80,
        termination_reason: null,
        created_at: 1_790_000_000,
      },
    ],
  });

  renderAt('/runs/run-1/details');

  expect(await screen.findByText('Run failed')).toBeInTheDocument();
  await userEvent.click(
    await screen.findByText('Supervisor allocation ledger'),
  );
  expect(
    screen.getByText('The first allocation committed before the failure.'),
  ).toBeInTheDocument();
});

it('keeps run details available when the Supervisor ledger endpoint is unavailable', async () => {
  vi.mocked(runsApi.getSupervisorPlan).mockRejectedValue(
    new Error('404 not found'),
  );

  renderAt('/runs/run-1/details');

  expect(await screen.findByText('Run Specifications')).toBeInTheDocument();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load the allocation ledger.',
  );
});

it('renders run details while the optional Supervisor ledger request is pending', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'completed',
  });
  vi.mocked(runsApi.getSupervisorPlan).mockReturnValue(new Promise(() => {}));

  renderAt('/runs/run-1/details');

  expect(await screen.findByText('Run Specifications')).toBeInTheDocument();
  expect(
    await screen.findByText('Loading the allocation ledger…'),
  ).toBeInTheDocument();
});

it('shows a skeleton while loading, then the goal details', async () => {
  renderAt('/runs/run-1/specifications');
  expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  expect(await screen.findByText('Run Specifications')).toBeInTheDocument();
});

it('renders the failed end state with the recorded error, not report tabs', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'failed',
    error: 'engine.node.generate exhausted its retry budget',
  });

  renderAt('/runs/run-1/details');

  expect(await screen.findByText('Run failed')).toBeInTheDocument();
  expect(
    screen.getByText('engine.node.generate exhausted its retry budget'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('link', {name: 'Goal Details'})).toBeNull();
  expect(screen.queryByRole('link', {name: 'All Ideas'})).toBeNull();
  expect(screen.queryByText('Run Specifications')).toBeNull();
});

it('renders the blocked end state with the recorded error, not report tabs', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'blocked',
    error: 'Safety screen held the run for human adjudication',
  });

  renderAt('/runs/run-1/overview');

  expect(await screen.findByText('Run blocked')).toBeInTheDocument();
  expect(
    screen.getByText('Safety screen held the run for human adjudication'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('link', {name: 'Research Overview'})).toBeNull();
  expect(screen.queryByText('Summary')).toBeNull();
});

it('renders the cancelled end state without report tabs', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'cancelled',
  });

  renderAt('/runs/run-1/details');

  expect(await screen.findByText('Run cancelled')).toBeInTheDocument();
  expect(screen.queryByRole('link', {name: 'Goal Details'})).toBeNull();
  expect(screen.queryByText('Run Specifications')).toBeNull();
});

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

// Local overflow clipping would defeat the ancestor's horizontal-scroll policy.
it('lets report-page content scroll horizontally on phone instead of clipping it', async () => {
  renderAt('/runs/run-1/details');
  await screen.findByText('Run Specifications');

  const page = document.querySelector('.cosci-report-page');
  expect(page?.className).toContain('max-[700px]:overflow-x-auto');
  expect(page?.className).toContain('max-[700px]:overflow-y-hidden');
  expect(page?.className).not.toContain('max-[700px]:overflow-hidden');
});

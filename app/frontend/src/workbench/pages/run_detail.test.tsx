import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {makeRun, renderAt} from './run_detail_test_support';

// Controllable stream mock: tests mutate `streamState` then rerender to drive
// the event-driven refetch effect. `setStream` replaces the events array so its
// identity changes and the effect re-runs.
const streamMock = vi.hoisted(() => ({
  state: {events: [] as {seq: number; type: string; payload: object}[]},
}));
vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({events: streamMock.state.events, terminal: false}),
}));

// Render tests observe event refreshes immediately; data-hook tests cover timing.
vi.mock('@/workbench/hooks/use_reset_timer', () => {
  const timer = {schedule: (run: () => void) => run(), cancel: () => {}};
  return {useResetTimer: () => timer};
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
  // A stubbed viewport must not leak into the next test's breakpoint.
  vi.unstubAllGlobals();
  setStream([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  vi.mocked(runsApi.getSupervisorPlan).mockResolvedValue({
    plan: null,
    allocations: [],
  });
  // Reset per-run collection mocks so overrides do not leak between tests.
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

  // The session switch in the shell header is what returns to the
  // transcript now (see SessionSwitch), so this arrow keeps one meaning on
  // every run -- leave the run -- rather than changing destination based on
  // whether a conversation happens to exist.
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

/**
 * Pins the viewport to one side of the phone breakpoint for a single test.
 *
 * `useIsMobile` reads `matchMedia`, which jsdom does not implement, so an
 * unstubbed test is always "desktop" -- which would let the mobile-only
 * assertion below pass for the wrong reason.
 *
 * @param mobile Whether the viewport should match the phone breakpoint.
 */
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

// MobileIdeaView (the ideas tab's mobile detail view) has no back control of
// its own -- the titlebar's back arrow is its only visible escape back to
// the ranked list, so an open idea must redirect it rather than leave the
// run entirely.
it('returns to the ranked ideas list when an idea is open', async () => {
  stubViewport(true);
  renderAt('/runs/run-1/ideas?idea=h-1');

  expect(
    await screen.findByRole('link', {name: 'Back to ranked ideas'}),
  ).toHaveAttribute('href', '/runs/run-1/ideas');
});

// The desktop split-pane shows the ranked list and the detail together, so
// the list is never somewhere the reader has navigated away from. Back keeps
// meaning "leave the run" there; retargeting it on every `?idea=` would
// strand a reader who pressed Back to get out of the run.
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
  // Elapsed time is measured, not projected, so it reads as a real duration
  // from the first second rather than as an estimate.
  expect(screen.getByText('Time elapsed')).toBeInTheDocument();
  expect(screen.getByText('< 1 minute')).toBeInTheDocument();
  expect(screen.getByText('Sources Analyzed')).toBeInTheDocument();
  expect(screen.getByText('Ideas explored')).toBeInTheDocument();
  expect(screen.getByText('Engine Node Generate')).toBeInTheDocument();
  const activityLog = screen.getByRole('region', {name: 'Activity log'});
  // The timeline maps the scientific_task's node (payload.task 'generate')
  // to its human phase title.
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

// A run that died shows its true state — status and recorded error — not
// report tabs whose content either does not exist or presents a partial run
// as finished.
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

// A run held at intake produces no ideas, so a reader on the Ideas tab must
// still learn it is waiting on a person -- not just a reader who happens to
// open Goal Details, where the safety audit itself lives. Also pins the DOM
// shape behind a real overlap bug: `.cosci-report-page` is a CSS grid whose
// grid-rows template is sized for a fixed set of direct children (titlebar,
// tabs, body), so a banner rendered as a fourth sibling landed in an unsized
// implicit track and its content overflowed into the heading below. jsdom
// runs no layout engine, so a pixel/getBoundingClientRect assertion here
// would compare fabricated zeros -- the verifiable regression check is that
// the notice lives inside the scrolling content region (alongside
// ReportUngroundedNotice) rather than beside it, so it never competes for a
// grid track.
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

// The report page grid is nested inside .ucs-page--report, an ancestor whose
// own overflow: hidden was relaxed to allow horizontal scrolling (see
// shell_surface.css) -- an unconditional overflow-hidden here would keep
// clipping locally before that ancestor ever saw the overflow, making the
// ancestor fix inert. Vertical scrolling stays owned by the inner
// .cosci-report-scroll region, so only the x axis is relaxed.
it('lets report-page content scroll horizontally on phone instead of clipping it', async () => {
  renderAt('/runs/run-1/details');
  await screen.findByText('Run Specifications');

  const page = document.querySelector('.cosci-report-page');
  expect(page?.className).toContain('max-[700px]:overflow-x-auto');
  expect(page?.className).toContain('max-[700px]:overflow-y-hidden');
  expect(page?.className).not.toContain('max-[700px]:overflow-hidden');
});

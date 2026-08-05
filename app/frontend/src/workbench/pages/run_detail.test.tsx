import {screen} from '@testing-library/react';
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

// Collapse the 600ms debounce to a synchronous passthrough with a stable
// identity, so a triggered refetch is observable in the same act() without
// timers. The wrapper is a module singleton (stable across renders); it always
// invokes the latest render's callback.
vi.mock('@/workbench/hooks/use_debounced_callback', () => {
  const latest: {fn: (...args: never[]) => void} = {fn: () => {}};
  const wrapper = Object.assign((...args: never[]) => latest.fn(...args), {
    cancel: () => {},
    flush: () => {},
  });
  return {
    useDebouncedCallback: (fn: (...args: never[]) => void) => {
      latest.fn = fn;
      return wrapper;
    },
  };
});

function setStream(events: {seq: number; type: string; payload: object}[]) {
  streamMock.state = {events};
}

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    getRun: vi.fn(),
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
  setStream([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  // Reset per-run collection mocks so overrides do not leak between tests.
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([]);
  vi.mocked(runsApi.getMatches).mockResolvedValue([]);
  vi.mocked(runsApi.getReport).mockResolvedValue(null);
  vi.mocked(runsApi.getSafety).mockResolvedValue([]);
  vi.mocked(runsApi.listInterviews).mockResolvedValue([]);
});

it('sends the back arrow to the conversation this run came from', async () => {
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

  // The rail sends a started session straight to its run, so this arrow is
  // the only way back to the transcript — it must not land on an empty
  // workspace, which is where every run used to send it.
  expect(
    await screen.findByRole('link', {name: 'Back to conversation'}),
  ).toHaveAttribute('href', '/chats/chat-7');
});

it('falls back to the workspace when no conversation started the run', async () => {
  renderAt('/runs/run-1/details');

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

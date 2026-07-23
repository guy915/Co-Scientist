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
});

it('shows live metrics and activity instead of report controls', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'running',
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
  expect(screen.getByText('Time remaining')).toBeInTheDocument();
  expect(screen.getByText('Estimating…')).toBeInTheDocument();
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

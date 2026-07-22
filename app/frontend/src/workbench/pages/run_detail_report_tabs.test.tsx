import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {makeRun, renderAt, tab} from './run_detail_test_support';

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

it('renders all four report tabs', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  for (const label of [
    'Goal Details',
    'Learning',
    'Research Overview',
    'All Ideas',
  ]) {
    expect(tab(new RegExp(label))).toBeInTheDocument();
  }
});

it('marks the Goal Details tab active for the base URL', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  expect(tab(/^Goal Details$/)).toHaveAttribute('aria-current', 'page');
  expect(tab(/All Ideas/)).not.toHaveAttribute('aria-current');
});

it('resolves a tab alias in the URL to its canonical tab', async () => {
  // "specs" aliases to Goal Details.
  renderAt('/runs/run-1/specs');
  await screen.findByText('Run Specifications');
  expect(tab(/Goal Details/)).toHaveAttribute('aria-current', 'page');
});

it('activates the tab named directly in the URL', async () => {
  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');
  expect(tab(/Research Overview/)).toHaveAttribute('aria-current', 'page');
});

it('navigates when a tab is clicked', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  fireEvent.click(tab(/Learning/));
  await waitFor(() =>
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/runs/run-1/learning',
    ),
  );
});

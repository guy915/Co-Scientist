import {screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {makeHypothesis, makeMatch} from '@/test_fixtures';
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

it('shows the run goal as the report heading', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue(
    makeRun('Reversing MASLD liver fibrosis'),
  );
  renderAt('/runs/run-1');
  expect(
    await screen.findByRole('heading', {
      level: 1,
      name: /Reversing MASLD liver fibrosis/i,
    }),
  ).toBeInTheDocument();
});

it('leads the overview with a stat sentence and winning ideas', async () => {
  const created = 1_700_000_000;
  vi.mocked(runsApi.getRun).mockResolvedValue(
    makeRun('Study pathway X', {
      created_at: created,
      completed_at: created + 3 * 3600,
    }),
  );
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([
    makeHypothesis({id: 'h1', title: 'Top idea alpha', elo_rating: 1735}),
    makeHypothesis({id: 'h2', title: 'Runner-up beta', elo_rating: 1707}),
  ]);
  vi.mocked(runsApi.getMatches).mockResolvedValue([
    makeMatch(1),
    makeMatch(2),
    makeMatch(3),
  ]);

  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');

  expect(
    await screen.findByText(
      new RegExp(
        'A total of 2 ideas were explored over 3 hours with the highest ' +
          'Elo rating of 1735 points and a total of 3 matches were ' +
          'played\\.',
      ),
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('heading', {name: /Winning ideas/}),
  ).toBeInTheDocument();
  expect(screen.getByText('Top idea alpha')).toBeInTheDocument();
});

it('omits stat clauses whose data is unavailable', async () => {
  // No timing on the run, no matches: the duration and matches clauses drop.
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([
    makeHypothesis({id: 'h1', title: 'Sole idea', elo_rating: 1500}),
  ]);

  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');

  const stat = await screen.findByText(/A total of 1 idea was explored/);
  expect(stat).toHaveTextContent(
    'A total of 1 idea was explored with the highest Elo rating of 1500 ' +
      'points.',
  );
  expect(stat.textContent).not.toContain('over');
  expect(stat.textContent).not.toContain('matches');
});

it('shows an error alert when loading fails', async () => {
  vi.mocked(runsApi.getRun).mockRejectedValue(new Error('boom'));
  renderAt('/runs/run-1');
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('boom');
});

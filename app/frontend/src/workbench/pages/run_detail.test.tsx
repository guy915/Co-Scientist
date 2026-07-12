import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import type {MatchRow, RunWithSummary} from '@/api/runs';
import {RunDetail} from './run_detail';
import {makeHypothesis} from '@/test-fixtures';

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
vi.mock('@/hooks/use_debounced_callback', () => {
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
    getCitations: vi.fn().mockResolvedValue([]),
    getReport: vi.fn().mockResolvedValue(null),
  };
});

const makeRun = (
  goal: string,
  timing?: {created_at: number; completed_at: number},
): RunWithSummary =>
  ({
    id: 'run-1',
    research_goal: goal,
    status: 'completed',
    config: {
      setup: {
        goal,
        requirements: ['Testable'],
        attributes: ['Novel'],
        criteria: ['Feasible'],
      },
    },
    ...timing,
  }) as unknown as RunWithSummary;

const makeMatch = (id: number): MatchRow => ({id}) as unknown as MatchRow;

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
        <Route path="/runs/:id/:tab" element={<RunDetail />} />
      </Routes>
      <LocationDisplay />
    </MemoryRouter>,
  );
}

const tab = (name: RegExp) => screen.getByRole('button', {name});

beforeEach(() => {
  vi.clearAllMocks();
  setStream([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  // Reset per-run collection mocks so overrides do not leak between tests.
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([]);
  vi.mocked(runsApi.getMatches).mockResolvedValue([]);
  vi.mocked(runsApi.getReport).mockResolvedValue(null);
});

describe('RunDetail', () => {
  it('shows a skeleton while loading, then the goal details', async () => {
    renderAt('/runs/run-1/specifications');
    expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
    expect(await screen.findByText('Run Specifications')).toBeInTheDocument();
  });

  it('refetches on a coalesced batch that ends in status but carries data', async () => {
    const getRun = vi.mocked(runsApi.getRun);
    // A fresh element each render — passing the same reference makes React bail
    // out of re-rendering, so the mutated stream would never be re-read.
    const makeUi = () => (
      <MemoryRouter initialEntries={['/runs/run-1/specifications']}>
        <Routes>
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/runs/:id/:tab" element={<RunDetail />} />
        </Routes>
      </MemoryRouter>
    );
    const {rerender} = render(makeUi());
    await screen.findByText('Run Specifications');
    const afterMount = getRun.mock.calls.length;

    // A pure-status delta must not refetch (preserves the original filter).
    setStream([{seq: 1, type: 'status', payload: {}}]);
    rerender(makeUi());
    expect(getRun.mock.calls.length).toBe(afterMount);

    // A batch whose newest event is 'status' but which carries a data event
    // must still refetch. The old tail-only check skipped this; the batch scan
    // fixes it. This assertion fails against the pre-fix implementation.
    setStream([
      {seq: 1, type: 'status', payload: {}},
      {seq: 2, type: 'generate', payload: {}},
      {seq: 3, type: 'status', payload: {}},
    ]);
    rerender(makeUi());
    await waitFor(() =>
      expect(getRun.mock.calls.length).toBeGreaterThan(afterMount),
    );
  });

  it('renders all four report tabs', async () => {
    renderAt('/runs/run-1');
    await screen.findByText('Ideas');
    for (const label of [
      'Ideas',
      'Knowledge Base',
      'Summary',
      'Run Specifications',
    ]) {
      expect(tab(new RegExp(label))).toBeInTheDocument();
    }
  });

  it('marks the Ideas tab active for the base URL', async () => {
    renderAt('/runs/run-1');
    await screen.findByText('Ideas');
    expect(tab(/^Ideas$/)).toHaveAttribute('aria-current', 'page');
    expect(tab(/Run Specifications/)).not.toHaveAttribute('aria-current');
  });

  it('resolves a tab alias in the URL to its canonical tab', async () => {
    // "specs" aliases to Run Specifications.
    renderAt('/runs/run-1/specs');
    await screen.findByText('Run Specifications');
    expect(tab(/Run Specifications/)).toHaveAttribute('aria-current', 'page');
  });

  it('activates the tab named directly in the URL', async () => {
    renderAt('/runs/run-1/overview');
    await screen.findByText('Research overview');
    expect(tab(/^Summary$/)).toHaveAttribute('aria-current', 'page');
  });

  it('navigates when a tab is clicked', async () => {
    renderAt('/runs/run-1');
    await screen.findByText('Ideas');
    fireEvent.click(tab(/Knowledge Base/));
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/runs/run-1/knowledge',
      ),
    );
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

  it('leads the overview with a combined stat sentence and winning ideas', async () => {
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
    await screen.findByText('Research overview');

    expect(
      await screen.findByText(
        /A total of 2 ideas were explored over 3 hours with the highest Elo rating of 1735 points and a total of 3 matches were played\./,
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
    await screen.findByText('Research overview');

    const stat = await screen.findByText(/A total of 1 idea was explored/);
    expect(stat).toHaveTextContent(
      'A total of 1 idea was explored with the highest Elo rating of 1500 points.',
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
});

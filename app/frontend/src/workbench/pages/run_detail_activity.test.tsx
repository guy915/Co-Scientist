import type {Run} from '@/api/runs';
import * as runsApi from '@/api/runs';
import {
  ChatHistoryProvider,
  RunHistoryProvider,
} from '@/workbench/hooks/history_context';
import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter, Route, Routes, useNavigate} from 'react-router-dom';
import {beforeEach, expect, it, vi} from 'vitest';
import {RunDetail} from './run_detail';
import {useRunDetailData} from './run_detail_data';
import {makeRun} from './run_detail_test_support';

const streamMock = vi.hoisted(() => ({
  state: {
    events: [] as {seq: number; type: string; payload: object}[],
    connection: 'open' as
      'connecting' | 'open' | 'reconnecting' | 'disconnected',
  },
}));
vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({
    events: streamMock.state.events,
    terminal: false,
    connection: streamMock.state.connection,
  }),
}));

function setStream(events: {seq: number; type: string; payload: object}[]) {
  streamMock.state = {...streamMock.state, events};
}

function setConnection(connection: typeof streamMock.state.connection) {
  streamMock.state = {...streamMock.state, connection};
}

vi.mock('@/workbench/hooks/timers', async importOriginal => {
  const actual =
    await importOriginal<typeof import('@/workbench/hooks/timers')>();
  const timer = {schedule: (run: () => void) => run(), cancel: () => {}};
  return {...actual, useResetTimer: () => timer};
});

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    loadRunHistory: vi.fn().mockResolvedValue([]),
    getRun: vi.fn(),
    getHypotheses: vi.fn().mockResolvedValue([]),
    getEvidence: vi.fn().mockResolvedValue([]),
    getMatches: vi.fn().mockResolvedValue([]),
    getReviews: vi.fn().mockResolvedValue([]),
    getClaimEvidence: vi.fn().mockResolvedValue([]),
    getSafety: vi.fn().mockResolvedValue([]),
    getReport: vi.fn().mockResolvedValue(null),
  };
});

const TAB_NAV = 'Goal report sections';

const pending = <T,>() => new Promise<T>(() => {});

// Run route parameter changes reuse the mounted component; the harness must
// navigate likewise.
function RunSwitcher({to}: {to: string}) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(to)}>
      switch run
    </button>
  );
}

function renderRunDetail(path: string, switchTo?: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RunHistoryProvider>
        <ChatHistoryProvider>
          <Routes>
            <Route path="/runs/:id/:tab" element={<RunDetail />} />
          </Routes>
          {switchTo && <RunSwitcher to={switchTo} />}
        </ChatHistoryProvider>
      </RunHistoryProvider>
    </MemoryRouter>,
  );
}

const runningRun = (id: string): Run =>
  ({...makeRun('Study pathway X'), id, status: 'running'}) as unknown as Run;

it('drops the previous run’s content when the route id changes', async () => {
  renderRunDetail('/runs/run-1/details', '/runs/run-2/details');
  expect(await screen.findByText('Run Specifications')).toBeInTheDocument();

  vi.mocked(runsApi.getRun).mockImplementation(pending);
  await userEvent.click(screen.getByRole('button', {name: 'switch run'}));

  await waitFor(() =>
    expect(screen.queryByText('Run Specifications')).toBeNull(),
  );
  expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
});

it('shows no report chrome for a run the history reports as running', async () => {
  vi.mocked(runsApi.loadRunHistory).mockResolvedValue([runningRun('run-1')]);
  vi.mocked(runsApi.getRun).mockImplementation(pending);

  renderRunDetail('/runs/run-1/details');

  await waitFor(() => expect(runsApi.loadRunHistory).toHaveBeenCalled());
  expect(screen.queryByRole('navigation', {name: TAB_NAV})).toBeNull();
  expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
});

it('never reports a settled state belonging to the previous run', async () => {
  // Effect resets occur after rendering; inspect every render to catch
  // stale-report frames.
  const renders: {id: string; loaded: boolean; runId?: string}[] = [];
  function Probe({id}: {id: string}) {
    const data = useRunDetailData(id);
    renders.push({id, loaded: data.loaded, runId: data.run?.id});
    return null;
  }

  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  const view = render(<Probe id="run-1" />);
  await waitFor(() => expect(renders.at(-1)?.loaded).toBe(true));

  vi.mocked(runsApi.getRun).mockImplementation(pending);
  view.rerender(<Probe id="run-2" />);
  await waitFor(() => expect(renders.at(-1)?.id).toBe('run-2'));

  expect(
    renders.filter(r => r.loaded && r.runId !== undefined && r.runId !== r.id),
  ).toEqual([]);
});

it('shows the report tabs while a settled run loads', async () => {
  vi.mocked(runsApi.loadRunHistory).mockResolvedValue([
    {...runningRun('run-1'), status: 'completed'} as Run,
  ]);
  vi.mocked(runsApi.getRun).mockImplementation(pending);

  renderRunDetail('/runs/run-1/details');

  expect(
    await screen.findByRole('navigation', {name: TAB_NAV}),
  ).toBeInTheDocument();
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(runsApi.loadRunHistory).mockResolvedValue([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  setStream([]);
  setConnection('open');
});

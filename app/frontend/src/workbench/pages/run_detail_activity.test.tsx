import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter, Route, Routes, useNavigate} from 'react-router-dom';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import type {Run, SupervisorPlanResponse} from '@/api/runs';
import {ChatHistoryProvider} from '@/workbench/hooks/chat_history_context';
import {RunHistoryProvider} from '@/workbench/hooks/run_history_context';
import {RunDetail} from './run_detail';
import {useRunDetailData} from './run_detail_data';
import {makeRun} from './run_detail_test_support';

const streamMock = vi.hoisted(() => ({
  state: {
    events: [] as {seq: number; type: string; payload: object}[],
    connection: 'open' as
      | 'connecting'
      | 'open'
      | 'reconnecting'
      | 'disconnected',
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
    getSupervisorPlan: vi.fn().mockResolvedValue({plan: null, allocations: []}),
    getReport: vi.fn().mockResolvedValue(null),
  };
});

// The results chrome, asserted by its landmark rather than by any one tab
// control so the assertion survives the tabs being links or buttons.
const TAB_NAV = 'Goal report sections';

// A fetch that never settles, standing in for the window between opening a
// run and its row arriving.
const pending = <T,>() => new Promise<T>(() => {});

// The run-detail route element is mounted once for /runs/:id/:tab, so
// switching runs is a param change rather than a remount. This harness
// navigates the same way the sidebar does, in-router, so the test exercises
// that reuse instead of hiding it behind a fresh render.
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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(runsApi.loadRunHistory).mockResolvedValue([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  vi.mocked(runsApi.getSupervisorPlan).mockResolvedValue({
    plan: null,
    allocations: [],
  });
  setStream([]);
  setConnection('open');
});

it('drops the previous run’s content when the route id changes', async () => {
  renderRunDetail('/runs/run-1/details', '/runs/run-2/details');
  expect(await screen.findByText('Run Specifications')).toBeInTheDocument();

  // The second run's row has not arrived yet; run-1's report must not stand
  // in for it in the meantime.
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

  // The run row is still in flight, so the history list is the only signal
  // that this run is executing -- and it is enough to keep the results tabs
  // off the paint that used to flash them. (The settled-run case below is the
  // counterpart proving the history is read at all, rather than the chrome
  // merely waiting for the fetch.)
  await waitFor(() => expect(runsApi.loadRunHistory).toHaveBeenCalled());
  expect(screen.queryByRole('navigation', {name: TAB_NAV})).toBeNull();
  expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
});

it('never reports a settled state belonging to the previous run', async () => {
  // The reset that clears the previous run runs in an effect, so it lands
  // after the render that follows an id change. On that render the page used
  // to still be told the run was loaded -- with the old run's row attached --
  // which is one painted frame of the last run's report before the skeleton.
  // Every render is inspected here because that frame is gone before any
  // `waitFor` gets to look.
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

it('refreshes the allocation ledger after an orchestrator commit', async () => {
  const makeLedger = (reason: string): SupervisorPlanResponse => ({
    plan: null,
    allocations: [
      {
        id: 1,
        run_id: 'run-1',
        seq: 0,
        iteration: 1,
        task_type: 'generate',
        status: 'queued',
        reason,
        planner_reason: null,
        priority: 80,
        termination_reason: null,
        created_at: 1_790_000_000,
      },
    ],
  });
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'running',
  });
  vi.mocked(runsApi.getSupervisorPlan)
    .mockResolvedValueOnce(makeLedger('Recorded before'))
    .mockResolvedValue(makeLedger('Recorded after'));

  function Probe({version}: {version: number}) {
    const data = useRunDetailData('run-1');
    return (
      <div>
        <span>{version}</span>
        {data.supervisorPlan.response?.allocations.map(row => (
          <p key={row.id}>{row.reason}</p>
        ))}
      </div>
    );
  }

  const view = render(<Probe version={0} />);
  expect(await screen.findByText('Recorded before')).toBeInTheDocument();
  setStream([
    {seq: 3, type: 'scientific_task', payload: {task: 'orchestrator'}},
  ]);
  view.rerender(<Probe version={1} />);

  expect(await screen.findByText('Recorded after')).toBeInTheDocument();
  expect(runsApi.getSupervisorPlan).toHaveBeenCalledTimes(2);
  expect(runsApi.getEvidence).toHaveBeenCalledTimes(1);
});

it('refreshes the allocation ledger when SSE reconnects without a new event', async () => {
  const makeLedger = (reason: string): SupervisorPlanResponse => ({
    plan: null,
    allocations: [
      {
        id: 1,
        run_id: 'run-1',
        seq: 0,
        iteration: 1,
        task_type: 'generate',
        status: 'queued',
        reason,
        planner_reason: null,
        priority: 80,
        termination_reason: null,
        created_at: 1_790_000_000,
      },
    ],
  });
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'running',
  });
  vi.mocked(runsApi.getSupervisorPlan)
    .mockResolvedValueOnce(makeLedger('Saved before reconnect'))
    .mockResolvedValueOnce(makeLedger('Saved during the event gap'));

  function Probe({version}: {version: number}) {
    const data = useRunDetailData('run-1');
    return (
      <p>
        {version}: {data.supervisorPlan.response?.allocations[0]?.reason}
      </p>
    );
  }

  const view = render(<Probe version={0} />);
  expect(await screen.findByText(/Saved before reconnect/)).toBeInTheDocument();

  setConnection('reconnecting');
  view.rerender(<Probe version={1} />);
  expect(runsApi.getSupervisorPlan).toHaveBeenCalledTimes(1);

  setConnection('open');
  view.rerender(<Probe version={2} />);

  expect(
    await screen.findByText(/Saved during the event gap/),
  ).toBeInTheDocument();
  expect(runsApi.getSupervisorPlan).toHaveBeenCalledTimes(2);
});

it('refreshes the ledger once when the initial SSE connection opens', async () => {
  const makeLedger = (reason: string): SupervisorPlanResponse => ({
    plan: null,
    allocations: [
      {
        id: 1,
        run_id: 'run-1',
        seq: 0,
        iteration: 1,
        task_type: 'generate',
        status: 'queued',
        reason,
        planner_reason: null,
        priority: 80,
        termination_reason: null,
        created_at: 1_790_000_000,
      },
    ],
  });
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'running',
  });
  vi.mocked(runsApi.getSupervisorPlan)
    .mockResolvedValueOnce(makeLedger('Before first stream open'))
    .mockResolvedValueOnce(
      makeLedger('Checkpoint saved before completion event'),
    );
  setConnection('connecting');

  function Probe({version}: {version: number}) {
    const data = useRunDetailData('run-1');
    return (
      <p>
        {version}: {data.supervisorPlan.response?.allocations[0]?.reason}
      </p>
    );
  }

  const view = render(<Probe version={0} />);
  expect(
    await screen.findByText(/Before first stream open/),
  ).toBeInTheDocument();
  expect(runsApi.getSupervisorPlan).toHaveBeenCalledTimes(1);

  setConnection('open');
  view.rerender(<Probe version={1} />);
  expect(
    await screen.findByText(/Checkpoint saved before completion event/),
  ).toBeInTheDocument();
  expect(runsApi.getSupervisorPlan).toHaveBeenCalledTimes(2);

  view.rerender(<Probe version={2} />);
  expect(runsApi.getSupervisorPlan).toHaveBeenCalledTimes(2);
});

it('hides the previous run ledger immediately when the route id changes', async () => {
  vi.mocked(runsApi.getSupervisorPlan)
    .mockResolvedValueOnce({
      plan: null,
      allocations: [
        {
          id: 1,
          run_id: 'run-1',
          seq: 0,
          iteration: 1,
          task_type: 'generate',
          status: 'queued',
          reason: 'Saved on run one',
          planner_reason: null,
          priority: 80,
          termination_reason: null,
          created_at: 1_790_000_000,
        },
      ],
    })
    .mockReturnValue(pending<SupervisorPlanResponse>());

  function Probe({id}: {id: string}) {
    const data = useRunDetailData(id);
    return (
      <>
        {data.supervisorPlan.loading && <p>Loading ledger for this run</p>}
        {data.supervisorPlan.response?.allocations.map(row => (
          <p key={row.id}>{row.reason}</p>
        ))}
      </>
    );
  }

  const view = render(<Probe id="run-1" />);
  expect(await screen.findByText('Saved on run one')).toBeInTheDocument();

  view.rerender(<Probe id="run-2" />);

  expect(screen.queryByText('Saved on run one')).toBeNull();
  expect(screen.getByText('Loading ledger for this run')).toBeInTheDocument();
  expect(runsApi.getSupervisorPlan).toHaveBeenLastCalledWith('run-2');
});

import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter, Route, Routes, useNavigate} from 'react-router-dom';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import type {Run} from '@/api/runs';
import {ChatHistoryProvider} from '@/workbench/hooks/chat_history_context';
import {RunHistoryProvider} from '@/workbench/hooks/run_history_context';
import {RunDetail} from './run_detail';
import {useRunDetailData} from './run_detail_data';
import {makeRun} from './run_detail_test_support';

vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({events: [], terminal: false}),
}));

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

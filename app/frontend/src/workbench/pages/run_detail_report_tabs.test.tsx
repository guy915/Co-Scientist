import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {
  type Evidence,
  type HypothesisOutcome,
  type OutcomeRefinementAction,
  type RunWithSummary,
} from '@/api/runs';
import {clearAccessToken, setAccessToken} from '@/lib/client_id';
import {makeHypothesis} from '@/test_fixtures';
import {makeRun, renderAt, tab} from './run_detail_test_support';

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
    getHypotheses: vi.fn().mockResolvedValue([]),
    getHypothesisOutcomes: vi.fn().mockResolvedValue([]),
    getHypothesisOutcomeRefinement: vi.fn(),
    requestHypothesisOutcomeRefinement: vi.fn(),
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
  clearAccessToken();
  setStream([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  // Reset collection overrides between tests.
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([]);
  vi.mocked(runsApi.getHypothesisOutcomes).mockResolvedValue([]);
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockRejectedValue(
    new runsApi.HttpError('404 run or outcome not found', 404),
  );
  vi.mocked(runsApi.getMatches).mockResolvedValue([]);
  vi.mocked(runsApi.getReport).mockResolvedValue(null);
  vi.mocked(runsApi.getSafety).mockResolvedValue([]);
});

const SAVED_OUTCOME: HypothesisOutcome = {
  id: 'out-1',
  run_id: 'run-1',
  hypothesis_id: 'h1',
  author: 'Dr. Ada',
  recorded_at: 1_700_000_000,
  method_protocol: 'Western blot',
  conditions: 'Cells treated for 24 hours',
  measured_observation: 'Signal rose by two fold',
  controls: 'Vehicle control',
  interpretation: 'Consistent with the hypothesis',
  referenced_evidence_ids: [],
};

function savedRefinement(
  overrides: Partial<OutcomeRefinementAction> = {},
): OutcomeRefinementAction {
  return {
    action_id: 'action-1',
    run_id: 'run-1',
    outcome_id: 'out-1',
    hypothesis_id: 'h1',
    task_idempotency_key: 'outcome-refinement:action-1',
    checkpoint_seq: 3,
    context_codepoints: 850,
    status: 'running',
    child_hypothesis_id: null,
    created_at: 1_700_000_000,
    replayed: true,
    ...overrides,
  };
}

it('shows owner refinement status on the active run without offering a new action', async () => {
  setAccessToken('researcher-session');
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'running',
    provider: 'engine',
  } as RunWithSummary);
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([
    makeHypothesis({id: 'h1', title: 'Pathway hypothesis'}),
  ]);
  vi.mocked(runsApi.getHypothesisOutcomes).mockResolvedValue([
    {...SAVED_OUTCOME, id: 'out-2', recorded_at: 1_800_000_000},
    SAVED_OUTCOME,
  ]);
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockImplementation(
    (_runId, _hypothesisId, outcomeId) =>
      outcomeId === 'out-1'
        ? Promise.resolve(savedRefinement())
        : Promise.reject(new runsApi.HttpError('404 no saved action', 404)),
  );

  renderAt('/runs/run-1/overview');

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Refinement is running.',
  );
  expect(
    screen.getByRole('button', {name: 'Check or retry refinement'}),
  ).toBeEnabled();
  expect(
    screen.queryByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).not.toBeInTheDocument();
  expect(runsApi.requestHypothesisOutcomeRefinement).not.toHaveBeenCalled();
  expect(runsApi.getHypothesisOutcomeRefinement).toHaveBeenCalledWith(
    'run-1',
    'h1',
    'out-1',
  );
  expect(runsApi.getHypothesisOutcomeRefinement).toHaveBeenCalledWith(
    'run-1',
    'h1',
    'out-2',
  );
});

it('keeps failed owner refinement status and retry on a terminal run', async () => {
  setAccessToken('researcher-session');
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'failed',
    error: 'worker exited',
    provider: 'engine',
  } as RunWithSummary);
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([
    makeHypothesis({id: 'h1', title: 'Pathway hypothesis'}),
  ]);
  vi.mocked(runsApi.getHypothesisOutcomes).mockResolvedValue([SAVED_OUTCOME]);
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockResolvedValue(
    savedRefinement({status: 'failed'}),
  );
  vi.mocked(runsApi.requestHypothesisOutcomeRefinement).mockResolvedValue(
    savedRefinement({status: 'queued'}),
  );

  renderAt('/runs/run-1/overview');

  expect(
    await screen.findByText(
      'Refinement failed and remains available for owner retry.',
    ),
  ).toHaveAttribute('role', 'status');
  fireEvent.click(
    screen.getByRole('button', {name: 'Check or retry refinement'}),
  );
  expect(
    await screen.findByText(
      'The saved refinement request was replayed; no second action was created. Current status: queued.',
    ),
  ).toHaveAttribute('role', 'status');
  expect(runsApi.requestHypothesisOutcomeRefinement).toHaveBeenCalledWith(
    'run-1',
    'h1',
    'out-1',
  );
  expect(
    screen.queryByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).not.toBeInTheDocument();
});

it('does not fetch or disclose saved refinement state on active or failed runs without owner access', async () => {
  for (const status of ['running', 'failed'] as const) {
    vi.mocked(runsApi.getRun).mockResolvedValue({
      ...makeRun('Study pathway X'),
      status,
      provider: 'engine',
    } as RunWithSummary);
    vi.mocked(runsApi.getHypotheses).mockResolvedValue([
      makeHypothesis({id: 'h1', title: 'Pathway hypothesis'}),
    ]);
    vi.mocked(runsApi.getHypothesisOutcomes).mockResolvedValue([SAVED_OUTCOME]);

    const view = renderAt('/runs/run-1/overview');
    expect(
      await screen.findByRole('link', {name: 'Researcher access'}),
    ).toBeInTheDocument();
    expect(runsApi.getHypothesisOutcomeRefinement).not.toHaveBeenCalled();
    expect(screen.queryByText(/Refinement is running/)).not.toBeInTheDocument();
    view.unmount();
    vi.clearAllMocks();
    vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
    vi.mocked(runsApi.getHypotheses).mockResolvedValue([]);
    vi.mocked(runsApi.getHypothesisOutcomes).mockResolvedValue([]);
    vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockRejectedValue(
      new runsApi.HttpError('404 run or outcome not found', 404),
    );
  }
});

it('shows recorded outcomes after SSE refresh and after reopening the report', async () => {
  setAccessToken('researcher-session');
  const outcome: HypothesisOutcome = {
    id: 'out-1',
    run_id: 'run-1',
    hypothesis_id: 'h1',
    author: 'Dr. Ada',
    recorded_at: 1_700_000_000,
    method_protocol: 'Western blot',
    conditions: 'Cells treated for 24 hours',
    measured_observation: 'Signal rose by two fold',
    units: 'fold change',
    controls: 'Vehicle control',
    interpretation: 'Consistent with the hypothesis',
    referenced_evidence_ids: ['ev-17'],
  };
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([
    makeHypothesis({id: 'h1', title: 'Pathway hypothesis'}),
  ]);
  vi.mocked(runsApi.getHypothesisOutcomes)
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([outcome])
    .mockResolvedValue([outcome]);

  const firstView = renderAt('/runs/run-1/overview');
  expect(
    await screen.findByText(
      'No scientist-recorded observations have been added to this run.',
    ),
  ).toBeInTheDocument();

  setStream([
    {seq: 5, type: 'scientist.outcome', payload: {hypothesis_id: 'h1'}},
  ]);
  fireEvent.click(tab(/All Ideas/));
  expect(
    await screen.findByText('Signal rose by two fold'),
  ).toBeInTheDocument();
  expect(runsApi.getHypothesisOutcomes).toHaveBeenCalledTimes(2);
  expect(
    screen.getByRole('group', {name: 'Record an observation'}),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('textbox', {name: 'Method or protocol'}),
  ).toBeInTheDocument();

  firstView.unmount();
  setStream([]);
  renderAt('/runs/run-1/overview');
  expect(
    await screen.findByText('Signal rose by two fold'),
  ).toBeInTheDocument();
  expect(runsApi.getHypothesisOutcomes).toHaveBeenCalledTimes(3);
});

it('keeps the report available and exposes a failed outcomes read locally', async () => {
  setAccessToken('researcher-session');
  vi.mocked(runsApi.getHypothesisOutcomes).mockRejectedValue(
    new Error('outcomes unavailable'),
  );

  renderAt('/runs/run-1/overview');
  expect(await screen.findByRole('heading', {name: 'Summary'})).toBeVisible();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load observations: outcomes unavailable',
  );
  expect(screen.queryByRole('alert')).not.toHaveTextContent('API unavailable');
  expect(
    screen.getByRole('button', {name: 'Refresh observations'}),
  ).toBeEnabled();
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
  renderAt('/runs/run-1/specs');
  await screen.findByText('Run Specifications');
  expect(tab(/Goal Details/)).toHaveAttribute('aria-current', 'page');
});

it('activates the tab named directly in the URL', async () => {
  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');
  expect(tab(/Research Overview/)).toHaveAttribute('aria-current', 'page');
});

it('renders each tab as a link to its canonical route', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  expect(tab(/^Goal Details$/)).toHaveAttribute('href', '/runs/run-1/details');
  expect(tab(/Learning/)).toHaveAttribute('href', '/runs/run-1/learning');
  expect(tab(/Research Overview/)).toHaveAttribute(
    'href',
    '/runs/run-1/overview',
  );
  expect(tab(/All Ideas/)).toHaveAttribute('href', '/runs/run-1/ideas');
});

it('links to the canonical tab even from an aliased URL', async () => {
  renderAt('/runs/run-1/specs');
  await screen.findByText('All Ideas');
  expect(tab(/^Goal Details$/)).toHaveAttribute('href', '/runs/run-1/details');
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

it("labels the content region with the active tab's name", async () => {
  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');
  expect(
    screen.getByRole('main', {name: 'Research Overview'}),
  ).toBeInTheDocument();
});

const UNGROUNDED_NOTICE = /No literature was retrieved for this run/;

const EVIDENCE_ROW = {
  id: 'ev-1',
  title: 'Retrieved paper',
  source: 'pubmed',
  url: 'https://example.org/paper',
  authors: [],
  year: 2024,
  available: true,
  retracted: false,
} as Evidence;

it('flags a completed run with no retrieved evidence as ungrounded', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'real',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/details');

  expect(await screen.findByText(UNGROUNDED_NOTICE)).toBeInTheDocument();
});

it('shows the ungrounded notice on every report tab', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'real',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/ideas');

  expect(await screen.findByText(UNGROUNDED_NOTICE)).toBeInTheDocument();
});

it('omits the ungrounded notice when the run retrieved evidence', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'real',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([EVIDENCE_ROW]);

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
});

it('exempts offline-backed runs from the ungrounded notice', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'offline',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
});

it('exempts legacy mock-provider runs from the ungrounded notice', async () => {
  // Pre-llm_backend rows use provider to identify offline provenance.
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'mock',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
});

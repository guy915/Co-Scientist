import {screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {makeRun, renderAt} from './run_detail_test_support';

const streamMock = vi.hoisted(() => ({terminal: false}));
vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({events: [], terminal: streamMock.terminal}),
}));

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
    getReport: vi.fn().mockResolvedValue(null),
  };
});

function failedRun(failureKind?: string) {
  return {
    ...makeRun('Study pathway X'),
    status: 'failed' as const,
    failure_kind: failureKind,
    error: 'LLM call budget exhausted after 2500 requests',
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  streamMock.terminal = false;
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  vi.mocked(runsApi.getSupervisorPlan).mockResolvedValue({
    plan: null,
    allocations: [],
  });
});

it('shows exact call-budget guidance with an accessible label and keeps the recorded error', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue(
    failedRun('llm_call_budget_exceeded'),
  );

  renderAt('/runs/run-1/details');

  const guidance = await screen.findByRole('region', {
    name: 'Suggested next step',
  });
  expect(guidance).toHaveTextContent(
    'The run reached its configured model-call limit before it completed. Start a new run with a narrower goal or fewer ideas.',
  );
  expect(screen.getByText('Recorded error')).toBeInTheDocument();
  expect(
    screen.getByText('LLM call budget exhausted after 2500 requests'),
  ).toBeInTheDocument();
});

it('shows exact timeout guidance and keeps the recorded error', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...failedRun('llm_timeout'),
    error: 'Provider request timed out after 180 seconds',
  });

  renderAt('/runs/run-1/details');

  const guidance = await screen.findByRole('region', {
    name: 'Suggested next step',
  });
  expect(guidance).toHaveTextContent(
    'The model provider did not respond within the request timeout. Try the research again later.',
  );
  expect(
    screen.getByText('Provider request timed out after 180 seconds'),
  ).toBeInTheDocument();
});

it.each(['llm_timeoutish', 'LLM_TIMEOUT'])(
  'keeps unknown failure kind %s generic',
  async failureKind => {
    vi.mocked(runsApi.getRun).mockResolvedValue({
      ...failedRun(failureKind),
      error: 'Internal task failure detail',
    });

    renderAt('/runs/run-1/details');

    expect(await screen.findByText('Run failed')).toBeInTheDocument();
    expect(
      screen.queryByRole('region', {name: 'Suggested next step'}),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('Internal task failure detail'),
    ).toBeInTheDocument();
  },
);

it.each(['blocked', 'cancelled'] as const)(
  'does not show provider guidance when a run is %s',
  async status => {
    vi.mocked(runsApi.getRun).mockResolvedValue({
      ...makeRun('Study pathway X'),
      status,
      failure_kind: 'llm_timeout',
      error: 'Safety or cancellation detail',
    });

    renderAt('/runs/run-1/details');

    expect(await screen.findByText(`Run ${status}`)).toBeInTheDocument();
    expect(
      screen.queryByRole('region', {name: 'Suggested next step'}),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('Safety or cancellation detail'),
    ).toBeInTheDocument();
  },
);

it('refreshes failure guidance and keeps its terminal toast aligned', async () => {
  streamMock.terminal = true;
  vi.mocked(runsApi.getRun)
    .mockResolvedValueOnce(failedRun())
    .mockResolvedValue(failedRun('llm_call_budget_exceeded'));

  renderAt('/runs/run-1/details');

  expect(
    await screen.findByRole('region', {name: 'Suggested next step'}),
  ).toBeInTheDocument();
  expect(runsApi.getRun).toHaveBeenCalledTimes(2);
  expect(
    screen.getByText('Run failed. See the suggested next step below.'),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/Run failed: LLM call budget exhausted/),
  ).not.toBeInTheDocument();
});

import {resetRunDetailMocks} from './run_detail_api_test_support';
import * as runsApi from '@/api/runs';
import {screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {makeRun, renderAt} from './run_detail_test_support';

function failedRun(failureKind?: string) {
  return {
    ...makeRun('Study pathway X'),
    status: 'failed' as const,
    failure_kind: failureKind,
    error: 'LLM call budget exhausted after 2500 requests',
  };
}

it('shows exact call-budget guidance with an accessible label and keeps the recorded error', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue(
    failedRun('llm_call_budget_exceeded'),
  );

  renderAt('/runs/run-1/details');

  const guidance = await screen.findByRole('region', {
    name: 'Suggested next step',
  });
  expect(guidance).toHaveTextContent(
    'The run reached its configured model-call limit before it completed. Start a new run with a narrower research goal.',
  );
  expect(screen.getByText('Recorded error')).toBeInTheDocument();
  expect(
    screen.getByText('LLM call budget exhausted after 2500 requests'),
  ).toBeInTheDocument();
});

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

beforeEach(() => {
  resetRunDetailMocks();
});

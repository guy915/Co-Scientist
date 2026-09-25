import {fireEvent, render, screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import type {HypothesisOutcome, OutcomeRefinementAction} from '@/api/runs';
import {clearAccessToken, setAccessToken} from '@/lib/client_id';
import {makeHypothesis} from '@/test_fixtures';
import {HypothesisOutcomeRefinement} from './hypothesis_outcome_refinement';
import {HypothesisOutcomeSection} from './hypothesis_outcomes';

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    getHypothesisOutcomeRefinement: vi.fn(),
    requestHypothesisOutcomeRefinement: vi.fn(),
  };
});

const savedOutcome: HypothesisOutcome = {
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

function refinementAction(
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
    status: 'queued',
    child_hypothesis_id: null,
    created_at: 1_700_000_000,
    replayed: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockRejectedValue(
    new runsApi.HttpError('404 run or outcome not found', 404),
  );
  clearAccessToken();
});

function renderOwnedOutcome() {
  setAccessToken('researcher-session');
  return render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[savedOutcome]}
      allowRefinement
      onRefresh={vi.fn()}
    />,
  );
}

it('announces saved-action loading before allowing a new refinement request', async () => {
  let resolveAction: ((action: OutcomeRefinementAction) => void) | undefined;
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockImplementation(
    () =>
      new Promise(resolve => {
        resolveAction = resolve;
      }),
  );
  renderOwnedOutcome();

  expect(screen.getByRole('status')).toHaveTextContent(
    'Checking saved refinement status…',
  );
  expect(
    screen.getByRole('button', {name: 'Checking refinement…'}),
  ).toBeDisabled();
  expect(runsApi.requestHypothesisOutcomeRefinement).not.toHaveBeenCalled();

  resolveAction?.(refinementAction());
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Refinement request is queued.',
  );
});

it('loads a saved queued action when the owner reopens its outcome', async () => {
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockResolvedValueOnce(
    refinementAction(),
  );
  renderOwnedOutcome();

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Refinement request is queued.',
  );
  expect(runsApi.getHypothesisOutcomeRefinement).toHaveBeenCalledWith(
    'run-1',
    'h1',
    'out-1',
  );
  expect(runsApi.requestHypothesisOutcomeRefinement).not.toHaveBeenCalled();
});

it('shows the saved follow-up hypothesis after a refresh', async () => {
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockResolvedValueOnce(
    refinementAction({status: 'completed', child_hypothesis_id: 'child-1'}),
  );
  renderOwnedOutcome();

  expect(
    await screen.findByText(
      'Follow-up hypothesis child-1 was created and will pass through the normal gates.',
    ),
  ).toBeInTheDocument();
  expect(runsApi.requestHypothesisOutcomeRefinement).not.toHaveBeenCalled();
});

it('shows a saved failed action after the owner reopens its outcome', async () => {
  vi.mocked(runsApi.getHypothesisOutcomeRefinement).mockResolvedValueOnce(
    refinementAction({status: 'failed'}),
  );
  renderOwnedOutcome();

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Refinement failed and remains available for owner retry.',
  );
});

it('treats an owner-visible 404 as no saved action after loading', async () => {
  renderOwnedOutcome();

  expect(
    await screen.findByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).toBeEnabled();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(runsApi.requestHypothesisOutcomeRefinement).not.toHaveBeenCalled();
});

it('refreshes failed saved-action loads with GET before allowing a new request', async () => {
  vi.mocked(runsApi.getHypothesisOutcomeRefinement)
    .mockRejectedValueOnce(new Error('503 API unavailable'))
    .mockRejectedValueOnce(
      new runsApi.HttpError('404 run or outcome not found', 404),
    );
  renderOwnedOutcome();

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load refinement status: 503 API unavailable',
  );
  expect(
    screen.queryByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole('button', {name: 'Refresh refinement status'}),
  ).toBeEnabled();

  fireEvent.click(
    screen.getByRole('button', {name: 'Refresh refinement status'}),
  );

  expect(
    await screen.findByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).toBeEnabled();
  expect(runsApi.getHypothesisOutcomeRefinement).toHaveBeenCalledTimes(2);
  expect(runsApi.getHypothesisOutcomeRefinement).toHaveBeenLastCalledWith(
    'run-1',
    'h1',
    'out-1',
  );
  expect(runsApi.requestHypothesisOutcomeRefinement).not.toHaveBeenCalled();
});

it('refreshes status-only failures with GET and never offers a new action', async () => {
  vi.mocked(runsApi.getHypothesisOutcomeRefinement)
    .mockRejectedValueOnce(new Error('503 API unavailable'))
    .mockResolvedValueOnce(refinementAction());
  setAccessToken('researcher-session');
  render(
    <HypothesisOutcomeRefinement
      runId="run-1"
      hypothesisId="h1"
      outcomeId="out-1"
      statusOnly
    />,
  );

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load refinement status: 503 API unavailable',
  );
  fireEvent.click(
    screen.getByRole('button', {name: 'Refresh refinement status'}),
  );
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Refinement request is queued.',
  );
  expect(runsApi.getHypothesisOutcomeRefinement).toHaveBeenCalledTimes(2);
  expect(runsApi.requestHypothesisOutcomeRefinement).not.toHaveBeenCalled();
  expect(
    screen.queryByRole('button', {
      name: 'Use outcome to refine this hypothesis',
    }),
  ).not.toBeInTheDocument();
});

it('does not fetch or expose refinement state without researcher access', () => {
  render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[savedOutcome]}
      allowRefinement
      onRefresh={vi.fn()}
    />,
  );

  expect(runsApi.getHypothesisOutcomeRefinement).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', {name: /refinement/i})).toBeNull();
  expect(screen.queryByText(/Current status/)).not.toBeInTheDocument();
});

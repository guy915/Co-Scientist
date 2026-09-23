import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import type {HypothesisOutcome} from '@/api/runs';
import {clearAccessToken, setAccessToken} from '@/lib/client_id';
import {makeHypothesis} from '@/test_fixtures';
import {
  HypothesisOutcomeSection,
  RunOutcomesReport,
} from './hypothesis_outcomes';

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {...actual, addHypothesisOutcome: vi.fn()};
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
  units: 'fold change',
  controls: 'Vehicle control',
  interpretation: 'Consistent with the hypothesis',
  referenced_evidence_ids: ['ev-17'],
  hypothesis_snapshot: {
    title: 'Saved pathway hypothesis',
    statement: 'An earlier statement of the hypothesis.',
  },
  referenced_evidence: [
    {
      id: 'ev-17',
      title: 'A source paper',
      source: 'PubMed',
      url: 'https://example.org/source',
      doi: '10.1000/example',
      pmid: '12345',
      sha256: null,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  clearAccessToken();
});

it('shows this hypothesis outcomes with provenance and readable evidence IDs', () => {
  setAccessToken('researcher-session');
  render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1', title: 'Pathway hypothesis'})}
      outcomes={[
        savedOutcome,
        {...savedOutcome, id: 'other', hypothesis_id: 'h2'},
      ]}
      loading={false}
      error={null}
      onRefresh={vi.fn()}
    />,
  );

  expect(
    screen.getByText('Scientist-recorded observations'),
  ).toBeInTheDocument();
  expect(screen.getByText('Western blot')).toBeInTheDocument();
  expect(screen.getByText('Dr. Ada')).toBeInTheDocument();
  expect(screen.getByText('ev-17')).toBeInTheDocument();
  expect(screen.getByRole('link', {name: 'A source paper'})).toHaveAttribute(
    'href',
    'https://example.org/source',
  );
  expect(screen.getByText(/DOI 10\.1000\/example/)).toBeInTheDocument();
  expect(screen.queryByText('other')).not.toBeInTheDocument();
  expect(
    screen.getByText(
      /entered by a scientist and are not independently validated/i,
    ),
  ).toBeInTheDocument();
});

it('uses the stored hypothesis title and evidence metadata in the report view', () => {
  setAccessToken('researcher-session');
  render(
    <RunOutcomesReport
      outcomes={[savedOutcome]}
      hypotheses={[]}
      loading={false}
      error={null}
      onRefresh={vi.fn()}
    />,
  );

  expect(screen.getByText(/Saved pathway hypothesis/)).toBeInTheDocument();
  expect(
    screen.getByRole('link', {name: 'A source paper'}),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/do not change the generated report/i),
  ).toBeInTheDocument();
});

it('keeps collection loading and error recovery accessible', async () => {
  setAccessToken('researcher-session');
  const onRefresh = vi.fn();
  const {rerender} = render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[]}
      loading
      error={null}
      onRefresh={onRefresh}
    />,
  );
  expect(screen.getByRole('status')).toHaveTextContent('Loading observations');

  rerender(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[]}
      loading={false}
      error="API unavailable"
      onRefresh={onRefresh}
    />,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('API unavailable');
  fireEvent.click(screen.getByRole('button', {name: 'Refresh observations'}));
  expect(onRefresh).toHaveBeenCalledOnce();
});

it('submits a labeled observation and announces success', async () => {
  setAccessToken('researcher-session');
  vi.mocked(runsApi.addHypothesisOutcome).mockResolvedValue(savedOutcome);
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[]}
      loading={false}
      error={null}
      onRefresh={onRefresh}
    />,
  );

  fireEvent.change(screen.getByRole('textbox', {name: 'Method or protocol'}), {
    target: {value: 'Western blot'},
  });
  fireEvent.change(screen.getByRole('textbox', {name: 'Conditions'}), {
    target: {value: 'Cells treated for 24 hours'},
  });
  fireEvent.change(
    screen.getByRole('textbox', {name: 'Measured observation'}),
    {
      target: {value: 'Signal rose by two fold'},
    },
  );
  fireEvent.change(screen.getByRole('textbox', {name: 'Units (optional)'}), {
    target: {value: 'fold change'},
  });
  fireEvent.change(screen.getByRole('textbox', {name: 'Controls'}), {
    target: {value: 'Vehicle control'},
  });
  fireEvent.change(screen.getByRole('textbox', {name: 'Interpretation'}), {
    target: {value: 'Consistent with the hypothesis'},
  });
  fireEvent.change(
    screen.getByRole('textbox', {name: /Referenced evidence IDs/}),
    {target: {value: 'ev-17, ev-18\nev-19'}},
  );
  fireEvent.click(screen.getByRole('button', {name: 'Record observation'}));

  await waitFor(() => expect(onRefresh).toHaveBeenCalledOnce());
  expect(runsApi.addHypothesisOutcome).toHaveBeenCalledWith('run-1', 'h1', {
    method_protocol: 'Western blot',
    conditions: 'Cells treated for 24 hours',
    measured_observation: 'Signal rose by two fold',
    units: 'fold change',
    controls: 'Vehicle control',
    interpretation: 'Consistent with the hypothesis',
    referenced_evidence_ids: ['ev-17', 'ev-18', 'ev-19'],
  });
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Observation recorded.',
  );
});

it('announces a server rejection and keeps the entered observation', async () => {
  setAccessToken('researcher-session');
  vi.mocked(runsApi.addHypothesisOutcome).mockRejectedValue(
    new Error('409 outcome rejected'),
  );
  render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[]}
      loading={false}
      error={null}
      onRefresh={vi.fn()}
    />,
  );
  const observation = screen.getByRole('textbox', {
    name: 'Measured observation',
  });
  fireEvent.change(observation, {target: {value: 'A recorded result'}});
  fireEvent.change(screen.getByRole('textbox', {name: 'Method or protocol'}), {
    target: {value: 'Protocol'},
  });
  fireEvent.change(screen.getByRole('textbox', {name: 'Conditions'}), {
    target: {value: 'Conditions'},
  });
  fireEvent.change(screen.getByRole('textbox', {name: 'Controls'}), {
    target: {value: 'Controls'},
  });
  fireEvent.change(screen.getByRole('textbox', {name: 'Interpretation'}), {
    target: {value: 'Interpretation'},
  });
  fireEvent.click(screen.getByRole('button', {name: 'Record observation'}));

  expect(await screen.findByRole('alert')).toHaveTextContent(
    '409 outcome rejected',
  );
  expect(observation).toHaveValue('A recorded result');
});

it('offers researcher access instead of private outcome loading errors or a form', () => {
  render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[]}
      loading
      error="401 researcher access required"
      onRefresh={vi.fn()}
    />,
  );

  expect(screen.getByRole('link', {name: 'Researcher access'})).toHaveAttribute(
    'href',
    '/access',
  );
  expect(screen.queryByText('Loading observations…')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(
    screen.queryByRole('group', {name: 'Record an observation'}),
  ).toBeNull();
});

it('keeps public demo outcomes readable without a signed session', () => {
  render(
    <HypothesisOutcomeSection
      runId="run-1"
      hypothesis={makeHypothesis({id: 'h1'})}
      outcomes={[savedOutcome]}
      loading={false}
      error={null}
      readOnly
      onRefresh={vi.fn()}
    />,
  );

  expect(screen.getByText('Signal rose by two fold')).toBeInTheDocument();
  expect(
    screen.getByText('Public demo observations are read-only.'),
  ).toBeInTheDocument();
  expect(screen.queryByRole('link', {name: 'Researcher access'})).toBeNull();
  expect(
    screen.queryByRole('group', {name: 'Record an observation'}),
  ).toBeNull();
});

it('offers researcher access in the report view when private outcomes are unavailable', () => {
  render(
    <RunOutcomesReport
      outcomes={[]}
      hypotheses={[]}
      loading
      error="401 researcher access required"
      onRefresh={vi.fn()}
    />,
  );

  expect(screen.getByRole('link', {name: 'Researcher access'})).toHaveAttribute(
    'href',
    '/access',
  );
  expect(screen.queryByText('Loading observations…')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

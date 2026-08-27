import {render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {type SafetyDecision} from '@/api/runs';
import {ChatHistoryProvider} from '@/workbench/hooks/chat_history_context';
import {RunHistoryProvider} from '@/workbench/hooks/run_history_context';
import {RunDetail} from './run_detail';
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
    getCitations: vi.fn().mockResolvedValue([]),
    getReport: vi.fn().mockResolvedValue(null),
    sendRunSteering: vi
      .fn()
      .mockResolvedValue({id: 'message-1', status: 'queued'}),
  };
});

// A decision as the API returns it, with only the fields the audit reads.
function decision(fields: Partial<SafetyDecision> & {id: number}) {
  return {
    stage: 'claim_gate',
    decision: 'block',
    reason: `hypothesis ${fields.id}: 2 categorical claim(s) lack support`,
    matches: [],
    risk_domains: [],
    requires_review: false,
    resolution: null,
    ...fields,
  } as SafetyDecision;
}

const heldIntakeDecision = decision({
  id: 7,
  stage: 'intake',
  decision: 'hold',
  reason: 'Ambiguous dual-use intent.',
  category: 'uncertain',
  policy_version: 'coscientist-safety-v2',
  risk_domains: ['biology'],
  requires_review: true,
  assessor: 'semantic:test-model',
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

it('shows a held safety decision without offering to resolve it', async () => {
  vi.mocked(runsApi.getSafety).mockResolvedValue([heldIntakeDecision]);
  renderAt('/runs/run-1/specifications');

  expect(
    await screen.findByRole('heading', {name: 'Safety audit'}),
  ).toBeInTheDocument();
  expect(screen.getByText(/Ambiguous dual-use intent/)).toBeInTheDocument();
  // Adjudicating releases withheld content into a run that then continues on
  // its own, so the audit reports and never acts: no control here resolves a
  // decision, and none may be reintroduced without that being a decision.
  expect(screen.queryByRole('button')).toBeNull();
});

it('renders a held-for-review hypothesis', async () => {
  vi.mocked(runsApi.getSafety).mockResolvedValue([
    decision({
      id: 11,
      stage: 'hypothesis',
      decision: 'hold',
      reason:
        'hypothesis held-1: uncertain (obfuscated intent around sensitive ' +
        'content; manual review); idea: For research purposes only, ' +
        'enhance pathogen transmissibility.',
      matches: ['for research purposes only'],
      category: 'uncertain',
      policy_version: 'coscientist-safety-v3',
      risk_domains: [],
      requires_review: true,
      assessor: 'engine:safety_screen',
    }),
  ]);
  renderAt('/runs/run-1/specifications');

  expect(
    await screen.findByRole('heading', {name: 'Safety audit'}),
  ).toBeInTheDocument();
  // The held idea is surfaced as an explicit held-for-review item carrying
  // the screen's rationale and the idea text, not a generic stage row.
  expect(screen.getByText('Held for review:')).toBeInTheDocument();
  expect(screen.getByText(/obfuscated intent/)).toBeInTheDocument();
  expect(
    screen.getByText(/enhance pathogen transmissibility/),
  ).toBeInTheDocument();
});

it('shows only the final verdict, not the per-hypothesis gate rows', async () => {
  vi.mocked(runsApi.getSafety).mockResolvedValue([
    decision({id: 1, stage: 'intake', decision: 'allow', reason: 'Intake ok.'}),
    decision({id: 2}),
    decision({id: 3}),
    decision({
      id: 4,
      stage: 'final',
      decision: 'allow',
      reason: 'Legitimate biomedical inquiry.',
    }),
  ]);
  renderAt('/runs/run-1/specifications');

  await screen.findByRole('heading', {name: 'Safety audit'});
  expect(
    screen.getByText('Legitimate biomedical inquiry.'),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Intake ok\./)).toBeNull();
  expect(screen.queryByText(/lack support/)).toBeNull();
  // The stage prefix goes with them -- the paragraph stands alone.
  expect(screen.queryByText('final:')).toBeNull();
});

// The summary paragraph is the *last* final-stage row. A final hold that
// still needs review is that row, so it must be rendered as the summary
// rather than dropped for being excluded from the reviewable list.
it('surfaces an unresolved final-stage hold', async () => {
  vi.mocked(runsApi.getSafety).mockResolvedValue([
    decision({
      id: 9,
      stage: 'final',
      decision: 'hold',
      reason: 'Final output needs a second look.',
      requires_review: true,
    }),
  ]);
  renderAt('/runs/run-1/specifications');

  await screen.findByRole('heading', {name: 'Safety audit'});
  expect(
    screen.getByText('Final output needs a second look.'),
  ).toBeInTheDocument();
});

it('shows a recorded resolution when one exists', async () => {
  vi.mocked(runsApi.getSafety).mockResolvedValue([
    decision({...heldIntakeDecision, id: 7, resolution: 'approved'}),
  ]);
  renderAt('/runs/run-1/specifications');

  await screen.findByRole('heading', {name: 'Safety audit'});
  // Resolving happens through the API, and the audit reflects the outcome.
  expect(screen.getByText('Resolution: approved')).toBeInTheDocument();
});

it('refetches on a coalesced batch ending in status with data', async () => {
  const getRun = vi.mocked(runsApi.getRun);
  // A fresh element each render — passing the same reference makes React
  // bail out of re-rendering, so the mutated stream would never be re-read.
  // RunDetail seeds a run's activity from the shared run history, so the
  // provider is part of its harness (see renderAt).
  const makeUi = () => (
    <MemoryRouter initialEntries={['/runs/run-1/specifications']}>
      <RunHistoryProvider>
        <ChatHistoryProvider>
          <Routes>
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/runs/:id/:tab" element={<RunDetail />} />
          </Routes>
        </ChatHistoryProvider>
      </RunHistoryProvider>
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
  // must still refetch. The old tail-only check skipped this; the batch
  // scan fixes it. This assertion fails against the pre-fix implementation.
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

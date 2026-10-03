import {act, renderHook} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import type {Hypothesis, HypothesisOutcome, RunWithSummary} from '@/api/runs';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {makeHypothesis, makeRun} from '@/test_fixtures';
import {useRunDetailData, useRunOutcomeCollection} from './run_detail_data';

const stream = vi.hoisted(() => ({
  events: [] as StreamEvent[],
  terminal: false,
  connection: 'open' as const,
}));

vi.mock('@/hooks/use_run_stream', () => ({useRunStream: () => stream}));
vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    getRun: vi.fn(),
    getHypotheses: vi.fn(),
    getEvidence: vi.fn(),
    getMatches: vi.fn(),
    getReviews: vi.fn(),
    getClaimEvidence: vi.fn(),
    getSafety: vi.fn(),
    getReport: vi.fn(),
    getHypothesisOutcomes: vi.fn(),
    getSupervisorPlan: vi.fn(),
  };
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return {promise, resolve, reject};
}

function run(id = 'run-1', status: RunWithSummary['status'] = 'running') {
  return {
    ...makeRun({id, status}),
    summary: {hypotheses: 0, evidence: 0, matches: 0, reviews: 0, events: 0},
  } satisfies RunWithSummary;
}

async function load() {
  const hook = renderHook(({id}) => useRunDetailData(id), {
    initialProps: {id: 'run-1'},
  });
  await act(async () => {});
  expect(hook.result.current.loaded).toBe(true);
  return hook;
}

async function emit(rerender: (props: {id: string}) => void, type: string) {
  stream.events = [
    ...stream.events,
    {seq: stream.events.length + 1, type, payload: {}},
  ];
  rerender({id: 'run-1'});
  await act(async () => vi.advanceTimersByTimeAsync(600));
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  stream.events = [];
  stream.terminal = false;
  vi.mocked(runsApi.getRun).mockResolvedValue(run());
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([]);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);
  vi.mocked(runsApi.getMatches).mockResolvedValue([]);
  vi.mocked(runsApi.getReviews).mockResolvedValue([]);
  vi.mocked(runsApi.getClaimEvidence).mockResolvedValue([]);
  vi.mocked(runsApi.getSafety).mockResolvedValue([]);
  vi.mocked(runsApi.getReport).mockResolvedValue(null);
  vi.mocked(runsApi.getHypothesisOutcomes).mockResolvedValue([]);
  vi.mocked(runsApi.getSupervisorPlan).mockResolvedValue({
    plan: null,
    allocations: [],
  });
});

afterEach(() => vi.useRealTimers());

it('keeps the terminal snapshot when an older partial refresh finishes later', async () => {
  const {result, rerender} = await load();
  const olderRun = deferred<RunWithSummary>();
  const olderIdeas = deferred<Hypothesis[]>();
  vi.mocked(runsApi.getRun).mockReturnValueOnce(olderRun.promise);
  vi.mocked(runsApi.getHypotheses).mockReturnValueOnce(olderIdeas.promise);
  await emit(rerender, 'generate');

  const finalIdeas = [makeHypothesis({id: 'final'})];
  vi.mocked(runsApi.getRun).mockResolvedValue(run('run-1', 'completed'));
  vi.mocked(runsApi.getHypotheses).mockResolvedValue(finalIdeas);
  stream.terminal = true;
  rerender({id: 'run-1'});
  await act(async () => {});
  expect(result.current.run?.status).toBe('completed');

  await act(async () => {
    olderRun.resolve(run());
    olderIdeas.resolve([makeHypothesis({id: 'older'})]);
  });
  expect(result.current.run?.status).toBe('completed');
  expect(result.current.hypotheses).toEqual(finalIdeas);
});

it('applies disjoint overlapping refreshes without reverting the newer run row', async () => {
  const {result, rerender} = await load();
  const olderRun = deferred<RunWithSummary>();
  const olderIdeas = deferred<Hypothesis[]>();
  vi.mocked(runsApi.getRun).mockReturnValueOnce(olderRun.promise);
  vi.mocked(runsApi.getHypotheses).mockReturnValueOnce(olderIdeas.promise);
  await emit(rerender, 'generate');

  const reviewedRun = {...run(), latest_stage: 'reflection'};
  vi.mocked(runsApi.getRun).mockResolvedValue(reviewedRun);
  await emit(rerender, 'reflection');
  expect(result.current.run?.latest_stage).toBe('reflection');
  expect(runsApi.getHypotheses).toHaveBeenCalledTimes(2);
  expect(runsApi.getReviews).toHaveBeenCalledTimes(2);

  const ideas = [makeHypothesis({id: 'generated'})];
  await act(async () => {
    olderRun.resolve(run());
    olderIdeas.resolve(ideas);
  });
  expect(result.current.hypotheses).toEqual(ideas);
  expect(result.current.run?.latest_stage).toBe('reflection');
});

it('does not let an older failed refresh replace a newer successful result', async () => {
  const {result, rerender} = await load();
  const olderRun = deferred<RunWithSummary>();
  vi.mocked(runsApi.getRun).mockReturnValueOnce(olderRun.promise);
  await emit(rerender, 'generate');

  vi.mocked(runsApi.getRun).mockResolvedValue(run('run-1', 'completed'));
  act(() => result.current.refreshNow());
  await act(async () => {});
  await act(async () => olderRun.reject(new Error('Old request failed')));
  expect(result.current.error).toBeNull();
  expect(result.current.run?.status).toBe('completed');
});

it('drops a previous run response after navigation', async () => {
  const {result, rerender} = await load();
  const olderRun = deferred<RunWithSummary>();
  vi.mocked(runsApi.getRun).mockReturnValueOnce(olderRun.promise);
  await emit(rerender, 'generate');

  stream.events = [];
  vi.mocked(runsApi.getRun).mockResolvedValue(run('run-2', 'completed'));
  rerender({id: 'run-2'});
  await act(async () => {});
  await act(async () => olderRun.resolve(run('run-1')));
  expect(result.current.run?.id).toBe('run-2');
});

it('coalesces mixed events into one selective refresh and cancels it on unmount', async () => {
  const {rerender, unmount} = await load();
  stream.events = [
    {seq: 1, type: 'generate', payload: {}},
    {seq: 2, type: 'reflection', payload: {}},
    {seq: 3, type: 'status', payload: {}},
  ];
  rerender({id: 'run-1'});
  await act(async () => vi.advanceTimersByTimeAsync(600));
  expect(runsApi.getRun).toHaveBeenCalledTimes(2);
  expect(runsApi.getHypotheses).toHaveBeenCalledTimes(2);
  expect(runsApi.getReviews).toHaveBeenCalledTimes(2);
  expect(runsApi.getEvidence).toHaveBeenCalledTimes(1);
  expect(runsApi.getReport).toHaveBeenCalledTimes(1);

  stream.events = [...stream.events, {seq: 4, type: 'ranking', payload: {}}];
  rerender({id: 'run-1'});
  unmount();
  await act(async () => vi.advanceTimersByTimeAsync(600));
  expect(runsApi.getRun).toHaveBeenCalledTimes(2);
});

it('retires manual refresh callbacks when the page unmounts', async () => {
  const {result, unmount} = await load();
  const refresh = result.current.refreshNow;
  unmount();
  await act(async () => refresh());
  expect(runsApi.getRun).toHaveBeenCalledTimes(1);
});

it('restarts the trailing refresh window and merges separately arriving events', async () => {
  const {rerender} = await load();
  stream.events = [{seq: 1, type: 'generate', payload: {}}];
  rerender({id: 'run-1'});
  await act(async () => vi.advanceTimersByTimeAsync(300));
  stream.events = [...stream.events, {seq: 2, type: 'reflection', payload: {}}];
  rerender({id: 'run-1'});

  await act(async () => vi.advanceTimersByTimeAsync(599));
  expect(runsApi.getRun).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(runsApi.getRun).toHaveBeenCalledTimes(2);
  expect(runsApi.getHypotheses).toHaveBeenCalledTimes(2);
  expect(runsApi.getReviews).toHaveBeenCalledTimes(2);
  expect(runsApi.getEvidence).toHaveBeenCalledTimes(1);
});

function outcome(id: string): HypothesisOutcome {
  return {
    id,
    run_id: 'run-1',
    hypothesis_id: 'hyp-1',
    author: 'Researcher',
    recorded_at: 1,
    method_protocol: 'Assay',
    conditions: 'Standard conditions',
    measured_observation: id,
    controls: 'Vehicle',
    interpretation: 'Observed',
    referenced_evidence_ids: [],
  };
}

it('keeps the newest same-run outcome response when GETs resolve out of order', async () => {
  const older = deferred<HypothesisOutcome[]>();
  const newer = deferred<HypothesisOutcome[]>();
  vi.mocked(runsApi.getHypothesisOutcomes)
    .mockReturnValueOnce(older.promise)
    .mockReturnValueOnce(newer.promise);
  const {result} = renderHook(() => useRunOutcomeCollection());

  act(() => result.current.reset('run-1'));
  let olderRequest!: Promise<void>;
  let newerRequest!: Promise<void>;
  act(() => {
    olderRequest = result.current.refresh('run-1');
    newerRequest = result.current.refresh('run-1');
  });

  await act(async () => {
    newer.resolve([outcome('newer')]);
    await newerRequest;
  });
  expect(result.current.outcomes.map(row => row.id)).toEqual(['newer']);
  expect(result.current.loading).toBe(false);

  await act(async () => {
    older.resolve([outcome('older')]);
    await olderRequest;
  });
  expect(result.current.outcomes.map(row => row.id)).toEqual(['newer']);
  expect(result.current.loading).toBe(false);
});

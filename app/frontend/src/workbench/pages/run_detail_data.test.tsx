import type {Hypothesis, RunWithSummary} from '@/api/runs';
import * as runsApi from '@/api/runs';
import type {StreamEvent} from '@/hooks/use_run_stream';
import {makeHypothesis, makeRunWithSummary} from '@/test_fixtures';
import {act, renderHook} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {useRunDetailData} from './run_detail_data';

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
  return makeRunWithSummary({id, status});
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

it('refreshes the live counters on durable node task events', async () => {
  const {rerender, result} = await load();
  vi.mocked(runsApi.getRun).mockResolvedValue(
    makeRunWithSummary({
      id: 'run-1',
      status: 'running',
      summary: {...run().summary, hypotheses: 16, evidence: 229},
    }),
  );
  stream.events = [
    {seq: 1, type: 'scientific_task', payload: {task: 'ranking'}},
    {seq: 2, type: 'scientific_task', payload: {task: 'supervisor'}},
  ];
  rerender({id: 'run-1'});
  await act(async () => vi.advanceTimersByTimeAsync(600));
  expect(runsApi.getHypotheses).toHaveBeenCalledTimes(2);
  expect(runsApi.getMatches).toHaveBeenCalledTimes(2);
  expect(result.current.run?.summary.hypotheses).toBe(16);
  expect(result.current.run?.summary.evidence).toBe(229);
});

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
});

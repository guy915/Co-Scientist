import {act, renderHook} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import type {HypothesisOutcome} from '@/api/runs';
import {getHypothesisOutcomes} from '@/api/runs';
import {useRunOutcomeCollection} from './run_detail_outcomes_data';

vi.mock('@/api/runs', () => ({getHypothesisOutcomes: vi.fn()}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(settle => {
    resolve = settle;
  });
  return {promise, resolve};
}

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

beforeEach(() => vi.clearAllMocks());

it('keeps the newest same-run outcome response when GETs resolve out of order', async () => {
  const older = deferred<HypothesisOutcome[]>();
  const newer = deferred<HypothesisOutcome[]>();
  vi.mocked(getHypothesisOutcomes)
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

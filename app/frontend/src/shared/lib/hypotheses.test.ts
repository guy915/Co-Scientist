import {expect, it} from 'vitest';

import {makeHypothesis} from '@/shared/testing/fixtures';

import {presentedHypotheses, ratingLabel, sortByEloDesc} from './hypotheses';

it('orders played hypotheses by descending Elo', () => {
  const ranked = sortByEloDesc([
    makeHypothesis({id: 'mid', elo_rating: 1200, win_count: 1}),
    makeHypothesis({id: 'top', elo_rating: 1400, win_count: 2}),
    makeHypothesis({id: 'low', elo_rating: 1100, loss_count: 1}),
  ]);

  expect(ranked.map(h => h.id)).toEqual(['top', 'mid', 'low']);
});

it('sinks an undermined idea below every sound one', () => {
  // Deep verification can undermine the highest-rated idea after its matches
  // finish.
  const ranked = sortByEloDesc([
    makeHypothesis({
      id: 'doubted',
      elo_rating: 1400,
      win_count: 3,
      verification_verdict: 'undermined',
    }),
    makeHypothesis({id: 'sound', elo_rating: 1150, loss_count: 1}),
    makeHypothesis({id: 'unplayed', elo_rating: 1200}),
  ]);

  expect(ranked.map(h => h.id)).toEqual(['sound', 'unplayed', 'doubted']);
});

it('drops the ideas a run withdrew from the presented list', () => {
  const kept = makeHypothesis({id: 'kept'});
  const presented = presentedHypotheses([
    kept,
    makeHypothesis({id: 'a', status: 'rejected'}),
    makeHypothesis({id: 'b', status: 'duplicate'}),
  ]);

  expect(presented).toEqual([kept]);
});

it('says "Unranked" for an unplayed idea still in good standing', () => {
  // Final-wave ideas can arrive after the last comparisons.
  expect(ratingLabel(makeHypothesis({status: 'active'}))).toBe('Unranked');
  expect(ratingLabel(makeHypothesis({status: null}))).toBe('Unranked');
});

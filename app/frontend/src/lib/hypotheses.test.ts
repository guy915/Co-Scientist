import {expect, it} from 'vitest';

import {makeHypothesis} from '@/test_fixtures';

import {presentedHypotheses, ratingLabel, sortByEloDesc} from './hypotheses';

it('orders played hypotheses by descending Elo', () => {
  const ranked = sortByEloDesc([
    makeHypothesis({id: 'mid', elo_rating: 1200, win_count: 1}),
    makeHypothesis({id: 'top', elo_rating: 1400, win_count: 2}),
    makeHypothesis({id: 'low', elo_rating: 1100, loss_count: 1}),
  ]);

  expect(ranked.map(h => h.id)).toEqual(['top', 'mid', 'low']);
});

it('ranks an idea that lost a match above one that never played', () => {
  // Initial Elo can put unplayed ideas above actual tournament losers.
  const ranked = sortByEloDesc([
    makeHypothesis({id: 'unplayed', elo_rating: 1200}),
    makeHypothesis({id: 'loser', elo_rating: 1136, loss_count: 1}),
    makeHypothesis({id: 'winner', elo_rating: 1259, win_count: 1}),
  ]);

  expect(ranked.map(h => h.id)).toEqual(['winner', 'loser', 'unplayed']);
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

it('does not mutate the input array', () => {
  const input = [
    makeHypothesis({id: 'a', elo_rating: 1100, win_count: 1}),
    makeHypothesis({id: 'b', elo_rating: 1300, win_count: 1}),
  ];

  sortByEloDesc(input);

  expect(input.map(h => h.id)).toEqual(['a', 'b']);
});

it('reports the earned rating for an idea that played', () => {
  expect(
    ratingLabel(
      makeHypothesis({elo_rating: 1268, win_count: 2, loss_count: 1}),
    ),
  ).toBe('Elo rating: 1268');
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

it('keeps the rating of a played idea that was later ruled out', () => {
  // Later verification does not invalidate matches already played.
  expect(
    ratingLabel(
      makeHypothesis({elo_rating: 1240, win_count: 1, status: 'rejected'}),
    ),
  ).toBe('Elo rating: 1240');
});

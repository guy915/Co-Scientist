import {expect, it} from 'vitest';

import {makeHypothesis} from '@/test_fixtures';

import {sortByEloDesc} from './hypotheses';

it('orders played hypotheses by descending Elo', () => {
  const ranked = sortByEloDesc([
    makeHypothesis({id: 'mid', elo_rating: 1200, win_count: 1}),
    makeHypothesis({id: 'top', elo_rating: 1400, win_count: 2}),
    makeHypothesis({id: 'low', elo_rating: 1100, loss_count: 1}),
  ]);

  expect(ranked.map(h => h.id)).toEqual(['top', 'mid', 'low']);
});

it('ranks an idea that lost a match above one that never played', () => {
  // Every hypothesis starts at 1200, so a pure Elo sort presents "never
  // competed" as better than "competed and lost". A production run led its
  // standings with six unplayed ideas at 1200 above the real runner-up at
  // 1136.
  const ranked = sortByEloDesc([
    makeHypothesis({id: 'unplayed', elo_rating: 1200}),
    makeHypothesis({id: 'loser', elo_rating: 1136, loss_count: 1}),
    makeHypothesis({id: 'winner', elo_rating: 1259, win_count: 1}),
  ]);

  expect(ranked.map(h => h.id)).toEqual(['winner', 'loser', 'unplayed']);
});

it('does not mutate the input array', () => {
  const input = [
    makeHypothesis({id: 'a', elo_rating: 1100, win_count: 1}),
    makeHypothesis({id: 'b', elo_rating: 1300, win_count: 1}),
  ];

  sortByEloDesc(input);

  expect(input.map(h => h.id)).toEqual(['a', 'b']);
});

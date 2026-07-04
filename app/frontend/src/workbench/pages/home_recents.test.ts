import {describe, expect, it} from 'vitest';
import type {Hypothesis} from '@/api/runs';
import {topEloFromHypotheses} from './home_recents';

const withElo = (elo: number): Hypothesis => ({elo_rating: elo}) as Hypothesis;

describe('topEloFromHypotheses', () => {
  it('returns the highest Elo rating', () => {
    expect(
      topEloFromHypotheses([withElo(1180), withElo(1320), withElo(1250)]),
    ).toBe(1320);
  });

  it('falls back to the baseline rating for an empty list', () => {
    expect(topEloFromHypotheses([])).toBe(1200);
  });

  it('ignores non-finite ratings', () => {
    expect(topEloFromHypotheses([withElo(Number.NaN), withElo(1210)])).toBe(
      1210,
    );
  });

  it('falls back to the baseline when every rating is non-finite', () => {
    expect(topEloFromHypotheses([withElo(Number.NaN), withElo(Infinity)])).toBe(
      1200,
    );
  });
});

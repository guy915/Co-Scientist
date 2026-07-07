import type {Hypothesis} from '@/api/runs';

/**
 * Returns a new array of hypotheses ordered by Elo rating, highest first.
 *
 * Canonical display ordering shared by the ideas and run-detail views so both
 * surfaces rank the same way and a change to the policy lives in one place.
 *
 * @param hypotheses The hypotheses to rank (not mutated).
 * @returns A new array sorted by descending Elo rating.
 */
export function sortByEloDesc(hypotheses: Hypothesis[]): Hypothesis[] {
  return [...hypotheses].sort((a, b) => b.elo_rating - a.elo_rating);
}

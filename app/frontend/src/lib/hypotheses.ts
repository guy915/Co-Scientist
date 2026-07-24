import type {Hypothesis} from '@/api/runs';

/**
 * Returns a new array of hypotheses ordered by Elo rating, highest first.
 *
 * Canonical display ordering shared by the ideas and run-detail views so both
 * surfaces rank the same way and a change to the policy lives in one place.
 *
 * Ideas that have played at least one match sort above ideas that have not,
 * whatever the numbers say. Every hypothesis starts at 1200, so an idea that
 * never entered the tournament outranks one that entered and lost — a run
 * shipped six unplayed ideas at 1200 above the genuine runner-up at 1136,
 * presenting "never competed" as better than "competed and lost".
 *
 * @param hypotheses The hypotheses to rank (not mutated).
 * @returns A new array with played ideas first, each group by descending Elo.
 */
export function sortByEloDesc(hypotheses: Hypothesis[]): Hypothesis[] {
  const played = (h: Hypothesis) => h.win_count + h.loss_count > 0;
  return [...hypotheses].sort((a, b) => {
    if (played(a) !== played(b)) return played(a) ? -1 : 1;
    return b.elo_rating - a.elo_rating;
  });
}

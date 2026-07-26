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

/**
 * Returns the rating chip text for one idea: its score, or why it has none.
 *
 * An idea only earns a rating by being compared against other ideas, so an
 * idea with no matches has no score to show. Three unrelated things produce
 * that state, and they must not share one label:
 *
 * - "Duplicate": proximity folded this idea into a higher-ranked one making
 *   the same proposal. Nobody judged it — it is redundant, not bad. This
 *   used to read "Disqualified", which told a scientist their work had
 *   failed peer review when it had only been deduplicated; one run showed
 *   twenty ideas that way.
 * - "Disqualified": the reviews or the evidence gate ruled the idea out on
 *   the merits (contradicted, unsound, or not novel), recorded as status
 *   "rejected". The reader needs to know it was withheld deliberately.
 * - "Unranked": everything else, which never got its turn — typically
 *   created in the run's last wave, after the final round of comparisons.
 *   Expected to be rare, since the tournament owes every eligible idea one
 *   match before a run ends; a run full of these is a bug, not a label.
 *
 * @param hypothesis The idea to label.
 * @returns Chip text: the Elo rating, or why there is none.
 */
export function ratingLabel(hypothesis: Hypothesis): string {
  if (hypothesis.win_count + hypothesis.loss_count > 0) {
    return `Elo rating: ${hypothesis.elo_rating}`;
  }
  if (hypothesis.status === 'duplicate') return 'Duplicate';
  return hypothesis.status === 'rejected' ? 'Disqualified' : 'Unranked';
}

import type {Hypothesis} from '@/api/runs';

/**
 * Statuses whose ideas the run withdrew and does not present as results.
 *
 * Mirrors the report's own exclusion set (``EXCLUDED_HYPOTHESIS_STATUSES``
 * in ``app/report_content_gates.py``): "duplicate" means proximity folded
 * the idea into a higher-ranked one making the same proposal, and "rejected"
 * means the reviews ruled it out on the merits. Neither is a result.
 */
const WITHDRAWN_STATUSES = new Set(['duplicate', 'rejected']);

/**
 * Returns the ideas a run actually put forward.
 *
 * Deduplicated and disqualified ideas were previously listed at the bottom
 * with a "Duplicate"/"Disqualified" chip in place of a rating. That is what
 * the Goal Report already leaves out, so the list disagreed with the report
 * it sits beside, and it padded a ranking with entries that were explicitly
 * not ranked. The run's own "ideas explored" count still covers them: the
 * list is the shortlist, not the audit trail.
 *
 * @param hypotheses The run's hypotheses (not mutated).
 * @returns Only the ideas still standing, in the given order.
 */
export function presentedHypotheses(hypotheses: Hypothesis[]): Hypothesis[] {
  return hypotheses.filter(
    hypothesis => !WITHDRAWN_STATUSES.has(String(hypothesis.status)),
  );
}

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
 * idea with no matches has no score to show and reads "Unranked" — it never
 * got its turn, typically created in the run's last wave after the final
 * round of comparisons. Expected to be rare, since the tournament owes every
 * eligible idea a win-loss record before a run ends; a list full of these is
 * a bug, not a label.
 *
 * Withdrawn ideas need no label of their own because they are not listed at
 * all (see {@link presentedHypotheses}).
 *
 * @param hypothesis The idea to label.
 * @returns Chip text: the Elo rating, or why there is none.
 */
export function ratingLabel(hypothesis: Hypothesis): string {
  if (hypothesis.win_count + hypothesis.loss_count > 0) {
    return `Elo rating: ${hypothesis.elo_rating}`;
  }
  return 'Unranked';
}

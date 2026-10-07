import type {Hypothesis} from '@/api/runs';

// Match the report exclusion set: duplicate/rejected ideas are withdrawn, not
// results.
const WITHDRAWN_STATUSES = new Set(['duplicate', 'rejected']);

// An undermined idea remains visible but demoted; match the engine verdict
// vocabulary.
export const UNDERMINED_VERDICT = 'undermined';

export function presentedHypotheses(hypotheses: Hypothesis[]): Hypothesis[] {
  return hypotheses.filter(
    hypothesis => !WITHDRAWN_STATUSES.has(String(hypothesis.status)),
  );
}

// Verification occurs after ranking and initial Elo is unearned: demote
// undermined ideas, then put played ideas before unplayed ones regardless of
// rating.
export function sortByEloDesc(hypotheses: Hypothesis[]): Hypothesis[] {
  const played = (h: Hypothesis) => h.win_count + h.loss_count > 0;
  const undermined = (h: Hypothesis) =>
    h.verification_verdict === UNDERMINED_VERDICT;
  return [...hypotheses].sort((a, b) => {
    if (undermined(a) !== undermined(b)) return undermined(a) ? 1 : -1;
    if (played(a) !== played(b)) return played(a) ? -1 : 1;
    return b.elo_rating - a.elo_rating;
  });
}

// Only an actual comparison earns a displayed rating; an untouched initial Elo
// must read as unranked.
export function ratingLabel(hypothesis: Hypothesis): string {
  if (hypothesis.win_count + hypothesis.loss_count > 0) {
    return `Elo rating: ${hypothesis.elo_rating}`;
  }
  return 'Unranked';
}

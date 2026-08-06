import type {
  ClaimEvidenceRow,
  Hypothesis,
  MatchRow,
  Review,
  SupportSpan,
} from '@/api/runs';

// The first review recorded for a hypothesis, if any: the initial
// peer-review row behind the "Review summary" section.
export function findHypothesisReview(
  hypothesis: Hypothesis,
  reviews: Review[],
): Review | undefined {
  return reviews.find(r => r.hypothesis_id === hypothesis.id);
}

// Every review row recorded for a hypothesis: the initial peer review plus
// whichever of the deep-verification and full/simulation/recurrent reviews
// ran. Order follows the store's creation order (audit E1/D13).
export function findHypothesisReviews(
  hypothesis: Hypothesis,
  reviews: Review[],
): Review[] {
  return reviews.filter(r => r.hypothesis_id === hypothesis.id);
}

// Reader-facing labels for the reviewer agents a review row can carry, so
// the initial, full, simulation, recurrent, and deep results stay visibly
// distinct instead of collapsing under a single "Full review" heading
// (finding D13). Unknown agents fall back to their raw name.
const REVIEWER_LABELS: Readonly<Record<string, string>> = {
  review: 'Initial peer review',
  reflection: 'Reflection review',
  full_review: 'Full review',
  simulation_review: 'Simulation review',
  recurrent_review: 'Recurrent review',
  deep_verification: 'Deep verification',
  scientist: 'Scientist review',
};

export function reviewerLabel(reviewerAgent: string): string {
  return REVIEWER_LABELS[reviewerAgent] || reviewerAgent || 'Unknown reviewer';
}

// Most recent match involving a hypothesis on either side, used for the
// "Match summary" section's outcome/rationale.
export function findLatestMatch(
  hypothesis: Hypothesis,
  matches: MatchRow[],
): MatchRow | undefined {
  return matches
    .filter(m => m.winner_id === hypothesis.id || m.loser_id === hypothesis.id)
    .sort((a, b) => b.created_at - a.created_at)[0];
}

// Human-readable origin label for the agent/source that produced a hypothesis.
export function originLabel(createdByAgent: string): string {
  switch (createdByAgent) {
    case 'evolution':
      return 'Evolution agent (refined from a parent)';
    case 'generation':
      return 'Generation agent';
    case 'scientist_manual':
      return 'Scientist (human-authored)';
    default:
      return createdByAgent || 'Unknown';
  }
}

// Per-label tallies backing claimEvidenceSummary's one-line count.
interface ClaimCounts {
  supports: number;
  partial: number;
  contradicts: number;
  categoricalUnsupported: number;
  speculative: number;
}

// Which tally a single claim belongs in. A "partial" (near-miss) verdict is a
// support tier of its own: relevant, consistent evidence short of full
// entailment.
function claimCountKey(c: ClaimEvidenceRow): keyof ClaimCounts {
  if (c.label === 'supports') return 'supports';
  if (c.label === 'partial') return 'partial';
  if (c.label === 'contradicts') return 'contradicts';
  if (c.claim_role === 'speculative') return 'speculative';
  return 'categoricalUnsupported';
}

function tallyClaimCounts(claims: ClaimEvidenceRow[]): ClaimCounts {
  const counts: ClaimCounts = {
    supports: 0,
    partial: 0,
    contradicts: 0,
    categoricalUnsupported: 0,
    speculative: 0,
  };
  for (const c of claims) counts[claimCountKey(c)]++;
  return counts;
}

// Tally keys in the order claimEvidenceSummary reports them.
const CLAIM_COUNT_LABELS: readonly {
  key: keyof ClaimCounts;
  suffix: string;
}[] = [
  {key: 'supports', suffix: 'supported'},
  {key: 'partial', suffix: 'partially supported'},
  {key: 'contradicts', suffix: 'contradicted'},
  {key: 'categoricalUnsupported', suffix: 'unsupported categorical'},
  {key: 'speculative', suffix: 'speculative'},
];

function describeClaimCounts(total: number, counts: ClaimCounts): string {
  const parts = [`${total} claim(s) assessed`];
  for (const {key, suffix} of CLAIM_COUNT_LABELS) {
    if (counts[key]) parts.push(`${counts[key]} ${suffix}`);
  }
  return parts.join(', ');
}

// Summarizes a hypothesis's claim-evidence edges as a one-line count by label
// (the claim-level grounding graph, Milestone 5), or null when none exist.
export function claimEvidenceSummary(
  claims: ClaimEvidenceRow[],
): string | null {
  if (!claims.length) return null;
  return describeClaimCounts(claims.length, tallyClaimCounts(claims));
}

// A support span normalized for display: the exact quote plus (when known) a
// link to open its source. Tolerates legacy rows that stored a bare string.
export interface NormalizedSpan {
  quote: string;
  url?: string;
}

export function normalizeSpans(
  items: (SupportSpan | string)[] | undefined,
): NormalizedSpan[] {
  if (!items) return [];
  return items.map(item =>
    typeof item === 'string'
      ? {quote: item}
      : {quote: item.quote, url: item.url || undefined},
  );
}

// "Review summary" section text, falling back to a placeholder until the
// review node has run.
export function reviewSummaryText(review: Review | undefined): string {
  return (
    review?.summary ||
    'Reviewer notes will appear after the review node completes.'
  );
}

// Placeholder for the review-critiques section until any review has run.
export const NO_REVIEW_CRITIQUES_TEXT =
  'No review critiques have been recorded yet.';

// One review row's critique, falling back to an explicit empty marker so a
// row with no critique text still reads as recorded-but-empty.
export function reviewCritiqueText(review: Review): string {
  return review.critique || 'No critique text was recorded.';
}

// "Tournament performance" section text: the win/loss record and win rate,
// or a placeholder when no matches have been recorded yet.
export function tournamentSummaryText(hypothesis: Hypothesis): string {
  const totalMatches = hypothesis.win_count + hypothesis.loss_count;
  if (!totalMatches) return 'No tournament matches have been recorded yet.';
  const winRate = Math.round((hypothesis.win_count / totalMatches) * 100);
  return (
    `${hypothesis.win_count} wins and ${hypothesis.loss_count} losses ` +
    `across ${totalMatches} pairwise matches (${winRate}% win rate).`
  );
}

// Human-readable debate-depth label. 1 = single-turn comparison; anything
// greater is a multi-turn scientific debate (top-ranked matchups) — the
// median-Elo allocation from the Google system (SSR §4, §12).
export function debateDepthLabel(turns: number | undefined): string {
  if (turns && turns > 1) {
    return `Multi-turn scientific debate (${turns} turns)`;
  }
  return 'Single-turn comparison';
}

import type {
  ClaimEvidenceRow,
  Hypothesis,
  MatchRow,
  Review,
  SupportSpan,
} from '@/api/runs';

// The one review recorded for a hypothesis, if any. At most one review per
// hypothesis is expected, so find() is fine here.
export function findHypothesisReview(
  hypothesis: Hypothesis,
  reviews: Review[],
): Review | undefined {
  return reviews.find(r => r.hypothesis_id === hypothesis.id);
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

// Summarizes a hypothesis's claim-evidence edges as a one-line count by label
// (the claim-level grounding graph, Milestone 5), or null when none exist.
export function claimEvidenceSummary(
  claims: ClaimEvidenceRow[],
): string | null {
  if (!claims.length) return null;
  const counts = {
    supports: 0,
    contradicts: 0,
    categoricalUnsupported: 0,
    speculative: 0,
  };
  for (const c of claims) {
    if (c.label === 'supports') counts.supports++;
    else if (c.label === 'contradicts') counts.contradicts++;
    else if (c.claim_role === 'speculative') counts.speculative++;
    else counts.categoricalUnsupported++;
  }
  const parts = [`${claims.length} claim(s) assessed`];
  if (counts.supports) parts.push(`${counts.supports} supported`);
  if (counts.contradicts) parts.push(`${counts.contradicts} contradicted`);
  if (counts.categoricalUnsupported) {
    parts.push(`${counts.categoricalUnsupported} unsupported categorical`);
  }
  if (counts.speculative) parts.push(`${counts.speculative} speculative`);
  return parts.join(', ');
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

// "Full review" section text, falling back to a placeholder until the review
// node has run.
export function reviewCritiqueText(review: Review | undefined): string {
  return review?.critique || 'No full review has been recorded yet.';
}

// "Tournament performance" section text: the win/loss record and win rate,
// or a placeholder when no matches have been recorded yet.
export function tournamentSummaryText(hypothesis: Hypothesis): string {
  const totalMatches = hypothesis.win_count + hypothesis.loss_count;
  if (!totalMatches) return 'No tournament matches have been recorded yet.';
  const winRate = Math.round((hypothesis.win_count / totalMatches) * 100);
  return `${hypothesis.win_count} wins and ${hypothesis.loss_count} losses across ${totalMatches} pairwise matches (${winRate}% win rate).`;
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

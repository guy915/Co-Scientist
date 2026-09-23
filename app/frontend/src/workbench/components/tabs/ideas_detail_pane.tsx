import {useMemo} from 'react';
import type {
  ClaimEvidenceRow,
  Hypothesis,
  HypothesisOutcome,
  MatchRow,
  Review,
} from '@/api/runs';
import {Icon} from '@/components/icon';
import {
  findHypothesisMatches,
  findHypothesisReview,
  findHypothesisReviews,
} from './ideas_detail_data';
import {SectionsRail} from './ideas_detail_rail';
import {
  DETAIL_PANE_ID,
  HypothesisDetailSections,
} from './ideas_detail_sections';

export {DETAIL_PANE_ID, SectionsRail};

const IDEA_DETAIL_PANE_CLASSES =
  'idea-detail-pane grid min-h-0 min-w-0 flex-1 content-start gap-[1.35rem] ' +
  'overflow-x-hidden overflow-y-auto border-r-0 bg-transparent px-7 ' +
  // Below 1024 the columns stack (see IDEA_SPLIT_GRID_CLASSES), so the pane
  // grows with its content rather than scrolling inside a fixed height that
  // would trap the detail in a sliver. 700px is the separate phone gutter.
  'pt-[1.45rem] pb-14 max-[1023px]:flex-none ' +
  'max-[1023px]:overflow-y-visible max-[700px]:px-4';

// `text-th-muted-fg` is the named alias of --md-sys-color-on-surface-variant
// (see theme_tokens.css); DESIGN.md keeps arbitrary token references out of
// component class strings.
const IDEA_DETAIL_EMPTY_CLASSES =
  `${IDEA_DETAIL_PANE_CLASSES} empty place-items-center text-center ` +
  'text-th-muted-fg';

/**
 * Detail pane for one hypothesis: overview/description, review summary and
 * full critique, tournament win/loss record, and the selected idea's full
 * match history. Renders an empty-state placeholder when nothing is
 * selected (e.g. no hypotheses yet).
 */
interface HypothesisDetailProps {
  hypothesis: Hypothesis | null;
  runId?: string;
  isDemo?: boolean;
  // The run's full review/match/claim sets; the detail filters them down to
  // the hypothesis itself, so call sites just forward what they have.
  reviews: Review[];
  matches: MatchRow[];
  claimEvidence?: ClaimEvidenceRow[];
  outcomes?: HypothesisOutcome[];
  outcomesLoading?: boolean;
  outcomesError?: string | null;
  onRefreshOutcomes?: () => Promise<void> | void;
}

// Memoized on their inputs so unrelated re-renders (e.g. SSE updates to
// sibling collections) skip re-scanning the run's full review/match/claim
// sets. Computed before the parent's empty-state return to satisfy the
// rules of hooks, hence the null guards.
function useHypothesisRecords(
  hypothesis: Hypothesis | null,
  reviews: Review[],
  matches: MatchRow[],
  claimEvidence: ClaimEvidenceRow[],
) {
  const review = useMemo(
    () => (hypothesis ? findHypothesisReview(hypothesis, reviews) : undefined),
    [hypothesis, reviews],
  );
  const allReviews = useMemo(
    () => (hypothesis ? findHypothesisReviews(hypothesis, reviews) : []),
    [hypothesis, reviews],
  );
  const matchHistory = useMemo(
    () => (hypothesis ? findHypothesisMatches(hypothesis, matches) : []),
    [hypothesis, matches],
  );
  const claims = useMemo(
    () =>
      hypothesis
        ? claimEvidence.filter(c => c.hypothesis_id === hypothesis.id)
        : [],
    [hypothesis, claimEvidence],
  );
  return {review, allReviews, matchHistory, claims};
}

export function HypothesisDetail({
  hypothesis,
  runId,
  isDemo,
  reviews,
  matches,
  claimEvidence = [],
  outcomes = [],
  outcomesLoading,
  outcomesError,
  onRefreshOutcomes,
}: HypothesisDetailProps) {
  const {review, allReviews, matchHistory, claims} = useHypothesisRecords(
    hypothesis,
    reviews,
    matches,
    claimEvidence,
  );

  if (!hypothesis) {
    return (
      <section id={DETAIL_PANE_ID} className={IDEA_DETAIL_EMPTY_CLASSES}>
        <Icon aria-hidden="true" name="format_list_numbered" />
        <p>Select a hypothesis to inspect the review and tournament details.</p>
      </section>
    );
  }

  return (
    <HypothesisDetailSections
      paneClasses={IDEA_DETAIL_PANE_CLASSES}
      hypothesis={hypothesis}
      runId={runId}
      isDemo={isDemo}
      review={review}
      allReviews={allReviews}
      matchHistory={matchHistory}
      claims={claims}
      outcomes={outcomes}
      outcomesLoading={outcomesLoading}
      outcomesError={outcomesError}
      onRefreshOutcomes={onRefreshOutcomes}
    />
  );
}

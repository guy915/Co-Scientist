import {useMemo, type ReactNode} from 'react';
import type {ClaimEvidenceRow, Hypothesis, MatchRow, Review} from '@/api/runs';
import {Icon} from '@/components/icon';
import {
  claimEvidenceSummary,
  debateDepthLabel,
  findHypothesisReview,
  findHypothesisReviews,
  findLatestMatch,
  normalizeSpans,
  type NormalizedSpan,
  originLabel,
  reviewSummaryText,
  tournamentSummaryText,
} from './ideas_detail_data';
import {SECTIONS, sectionSlug, SectionsRail} from './ideas_detail_rail';
import {ReviewCritiquesContent} from './ideas_detail_review_findings';

// The rail moved to ideas_detail_rail.tsx when this module reached the
// 500-line ceiling; re-exported here so callers keep importing both halves
// of the detail view from one place.
export {SectionsRail};

// Anchor for the selected rank-list row's aria-controls (an explicit "drives
// this pane" relation). Shared by the populated and empty-state renders below
// (mutually exclusive, never duplicated), distinct from any sectionSlug()
// output.
export const DETAIL_PANE_ID = 'hypothesis-detail-pane';

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

const IDEA_DETAIL_SECTION_CLASSES =
  'idea-detail-section grid gap-[0.45rem] border-t-0 pt-0 ' +
  '[&_h2]:m-0 [&_h2]:mb-2 [&_h2]:font-gsans [&_h2]:text-[2rem] ' +
  '[&_h2]:leading-10 [&_h2]:font-normal ' +
  'max-[700px]:[&_h2]:text-[clamp(1.5rem,6.8vw,2rem)] ' +
  'max-[700px]:[&_h2]:leading-[1.2] ' +
  '[&_h2]:text-cosci-idea-title-text [&_h3]:m-0 ' +
  '[&_h3]:text-base [&_h3]:font-semibold [&_h3]:normal-case ' +
  '[&_h3]:text-cosci-idea-title-text [&_p]:m-0 ' +
  '[&_p]:[overflow-wrap:anywhere] [&_p]:text-base ' +
  '[&_p]:leading-6 [&_p]:text-cosci-idea-detail-text';

/**
 * Detail pane for one hypothesis: overview/description, review summary and
 * full critique, tournament win/loss record, and the most recent match's
 * outcome and rationale. Renders an empty-state placeholder when nothing is
 * selected (e.g. no hypotheses yet).
 */
interface HypothesisDetailProps {
  hypothesis: Hypothesis | null;
  // The run's full review/match/claim sets; the detail filters them down to
  // the hypothesis itself, so call sites just forward what they have.
  reviews: Review[];
  matches: MatchRow[];
  claimEvidence?: ClaimEvidenceRow[];
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
  const latestMatch = useMemo(
    () => (hypothesis ? findLatestMatch(hypothesis, matches) : undefined),
    [hypothesis, matches],
  );
  const claims = useMemo(
    () =>
      hypothesis
        ? claimEvidence.filter(c => c.hypothesis_id === hypothesis.id)
        : [],
    [hypothesis, claimEvidence],
  );
  return {review, allReviews, latestMatch, claims};
}

export function HypothesisDetail({
  hypothesis,
  reviews,
  matches,
  claimEvidence = [],
}: HypothesisDetailProps) {
  const {review, allReviews, latestMatch, claims} = useHypothesisRecords(
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
      hypothesis={hypothesis}
      review={review}
      allReviews={allReviews}
      latestMatch={latestMatch}
      claims={claims}
    />
  );
}

interface DetailSectionsProps {
  hypothesis: Hypothesis;
  review: Review | undefined;
  allReviews: Review[];
  latestMatch: MatchRow | undefined;
  claims: ClaimEvidenceRow[];
}

// The ordered detail sections for a selected hypothesis. Props-only (no
// hooks), so the parent keeps every hook above its empty-state return.
function HypothesisDetailSections({
  hypothesis,
  review,
  allReviews,
  latestMatch,
  claims,
}: DetailSectionsProps) {
  return (
    <section
      id={DETAIL_PANE_ID}
      className={IDEA_DETAIL_PANE_CLASSES}
      aria-label="Hypothesis detail"
    >
      <DetailSection title={SECTIONS.overview}>
        <p>{hypothesis.statement}</p>
      </DetailSection>

      <DetailSection title={SECTIONS.description}>
        <HypothesisDescriptionContent hypothesis={hypothesis} />
      </DetailSection>

      <DetailSection title={SECTIONS.provenance}>
        <HypothesisProvenanceContent hypothesis={hypothesis} claims={claims} />
      </DetailSection>
      <DetailSection title={SECTIONS.reviewSummary}>
        <p>{reviewSummaryText(review)}</p>
      </DetailSection>
      <DetailSection title={SECTIONS.reviewCritiques}>
        <ReviewCritiquesContent reviews={allReviews} />
      </DetailSection>
      <DetailSection title={SECTIONS.tournament}>
        <p>{tournamentSummaryText(hypothesis)}</p>
      </DetailSection>
      <DetailSection title={SECTIONS.matchSummary}>
        <MatchSummaryContent latestMatch={latestMatch} />
      </DetailSection>
    </section>
  );
}

// "Description" section body: title plus the optional mechanism/expected-
// effect paragraphs. Props-only (no hooks), so it is safe to render outside
// HypothesisDetail's own scope.
function HypothesisDescriptionContent({hypothesis}: {hypothesis: Hypothesis}) {
  return (
    <>
      <h3>{hypothesis.title}</h3>
      {hypothesis.mechanism && (
        <p>
          <strong>Proposed mechanism of action:</strong> {hypothesis.mechanism}
        </p>
      )}
      {hypothesis.expected_effect && (
        <p>
          <strong>Expected effect:</strong> {hypothesis.expected_effect}
        </p>
      )}
    </>
  );
}

// Renders the located evidence spans behind each supported/contradicted claim,
// so a reader can read the exact quote that grounds the verdict and open its
// source (Milestone 5 / P0.5). Insufficient claims remain visible even though
// they have no source span, with their categorical/speculative role explicit.
// A "partial" verdict is a near-miss support tier: relevant, consistent
// evidence short of full entailment, cited from the same supporting spans.
function claimVerdictText(claim: ClaimEvidenceRow): string {
  if (claim.label === 'partial') return 'partial support';
  if (claim.label === 'insufficient') {
    return claim.claim_role === 'speculative'
      ? 'Speculative — evidence insufficient'
      : 'Unsupported categorical claim';
  }
  return claim.label;
}

function ClaimVerdictLabel({claim}: {claim: ClaimEvidenceRow}) {
  return (
    <span className="capitalize font-medium">{claimVerdictText(claim)}</span>
  );
}

// The located quotes behind one claim's verdict, each with its source link.
function EvidenceSpanList({spans}: {spans: NormalizedSpan[]}) {
  if (!spans.length) return null;
  return (
    <ul className="mt-1 flex flex-col gap-1">
      {spans.map((span, i) => (
        <li
          key={i}
          className="border-l-2 border-th-outline-variant pl-2 italic"
        >
          “{span.quote}”
          {span.url && (
            <>
              {' '}
              <a
                href={span.url}
                target="_blank"
                rel="noopener noreferrer"
                className="not-italic underline"
              >
                open source
              </a>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

// The located quotes a verdict rests on: a contradiction cites what
// contradicts the claim, every other verdict what supports it.
function claimSpans(claim: ClaimEvidenceRow): NormalizedSpan[] {
  return claim.label === 'contradicts'
    ? normalizeSpans(claim.contradicting)
    : normalizeSpans(claim.supporting);
}

function ClaimEvidenceDetail({claims}: {claims: ClaimEvidenceRow[]}) {
  if (!claims.length) return null;
  return (
    <div className="mt-1 flex flex-col gap-2">
      {claims.map(claim => (
        <div key={claim.id} className="text-xs">
          <p>
            <ClaimVerdictLabel claim={claim} />: {claim.claim}
          </p>
          <EvidenceSpanList spans={claimSpans(claim)} />
        </div>
      ))}
    </div>
  );
}

// "Provenance & lineage" section body: where the hypothesis came from
// (Milestone 1 immutable-evolution lineage), its proximity cluster
// (Milestone 3), its safety status (Milestone 6), and a summary of its
// claim-evidence grounding (Milestone 5).
function ProvenanceOriginLines({hypothesis}: {hypothesis: Hypothesis}) {
  return (
    <>
      <p>
        <strong>Origin:</strong> {originLabel(hypothesis.created_by_agent)}
        {hypothesis.author ? ` — ${hypothesis.author}` : ''}
      </p>
      <p>
        <strong>Generation:</strong>{' '}
        {hypothesis.generation === 0
          ? 'Generation 0 (initial hypothesis)'
          : `Generation ${hypothesis.generation}`}
        {hypothesis.parent_id && ' — evolved from an earlier hypothesis'}
      </p>
    </>
  );
}

function HypothesisProvenanceContent({
  hypothesis,
  claims,
}: {
  hypothesis: Hypothesis;
  claims: ClaimEvidenceRow[];
}) {
  const claimSummary = claimEvidenceSummary(claims);
  return (
    <>
      <ProvenanceOriginLines hypothesis={hypothesis} />
      {hypothesis.cluster_id && (
        <p>
          <strong>Proximity cluster:</strong> {hypothesis.cluster_id}
        </p>
      )}
      <p>
        <strong>Safety status:</strong>{' '}
        <span className="capitalize">
          {hypothesis.safety_status || 'not screened'}
        </span>
      </p>
      {claimSummary && (
        <p>
          <strong>Claim evidence:</strong> {claimSummary}
        </p>
      )}
      <ClaimEvidenceDetail claims={claims} />
    </>
  );
}

// "Outcome" line of the match summary: the match tier, when known.
function MatchOutcomeLine({tier}: {tier: string | null | undefined}) {
  if (!tier) return null;
  return (
    <p>
      <strong>Outcome:</strong> <span className="capitalize">{tier}</span>
    </p>
  );
}

// "Debate depth" line of the match summary, shown only once a match exists.
function MatchDebateDepthLine({
  latestMatch,
}: {
  latestMatch: MatchRow | undefined;
}) {
  if (!latestMatch) return null;
  return (
    <p>
      <strong>Debate depth:</strong>{' '}
      {debateDepthLabel(latestMatch.debate_turns)}
    </p>
  );
}

// "Match summary" section body: the optional outcome line, the debate depth,
// plus the rationale (or its placeholder). Props-only (no hooks).
function MatchSummaryContent({
  latestMatch,
}: {
  latestMatch: MatchRow | undefined;
}) {
  return (
    <>
      <MatchOutcomeLine tier={latestMatch?.tier} />
      <MatchDebateDepthLine latestMatch={latestMatch} />
      <p>{latestMatch?.rationale || 'No match rationale is available yet.'}</p>
    </>
  );
}

// One titled block within the detail pane. `id` (from sectionSlug) is the
// anchor target for SectionsRail's links and the deep-link hash.
function DetailSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className={IDEA_DETAIL_SECTION_CLASSES} id={sectionSlug(title)}>
      <h2>{title}</h2>
      <div>{children}</div>
    </section>
  );
}

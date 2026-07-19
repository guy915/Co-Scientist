import {useMemo, type MouseEvent, type ReactNode} from 'react';
import type {ClaimEvidenceRow, Hypothesis, MatchRow, Review} from '@/api/runs';
import {Icon} from '@/components/icon';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import {
  claimEvidenceSummary,
  debateDepthLabel,
  findHypothesisReview,
  findLatestMatch,
  normalizeSpans,
  originLabel,
  reviewCritiqueText,
  reviewSummaryText,
  tournamentSummaryText,
} from './ideas_detail_data';

const IDEA_DETAIL_PANE_CLASSES =
  'idea-detail-pane grid min-h-0 min-w-0 flex-1 content-start gap-[1.35rem] ' +
  'overflow-x-hidden overflow-y-auto border-r-0 bg-transparent px-7 ' +
  'pt-[1.45rem] pb-14 max-[720px]:flex-none max-[720px]:overflow-y-visible ' +
  'max-[720px]:px-4';

// The scroll pane a section rail jump targets: the detail pane itself (which
// scrolls below 720px) or its `.cosci-report-scroll` ancestor (the desktop
// scroller, owned by run_detail.tsx). Passed to the generic smoothScroll
// helper so that lib carries no app-specific class knowledge.
const IDEA_SCROLL_PANE_SELECTOR = '.idea-detail-pane, .cosci-report-scroll';

const IDEA_DETAIL_EMPTY_CLASSES =
  `${IDEA_DETAIL_PANE_CLASSES} empty place-items-center text-center ` +
  'text-[var(--md-sys-color-on-surface-variant)]';

const IDEA_DETAIL_SECTION_CLASSES =
  'idea-detail-section grid gap-[0.45rem] border-t-0 pt-0 ' +
  '[&_h2]:m-0 [&_h2]:mb-2 [&_h2]:font-gsans [&_h2]:text-[2rem] ' +
  '[&_h2]:leading-10 [&_h2]:font-normal ' +
  'max-[720px]:[&_h2]:text-[clamp(1.5rem,6.8vw,2rem)] ' +
  'max-[720px]:[&_h2]:leading-[1.2] ' +
  '[&_h2]:text-cosci-idea-title-text [&_h3]:m-0 ' +
  '[&_h3]:text-base [&_h3]:font-semibold [&_h3]:normal-case ' +
  '[&_h3]:text-cosci-idea-title-text [&_p]:m-0 ' +
  '[&_p]:[overflow-wrap:anywhere] [&_p]:text-base ' +
  '[&_p]:leading-6 [&_p]:text-cosci-idea-detail-text';

const IDEA_SECTIONS_RAIL_CLASSES =
  'idea-sections-rail m-5 min-w-0 min-w-[12.5rem] self-start ' +
  'rounded-[10px] bg-cosci-panel p-5 max-[720px]:hidden';

const IDEA_SECTIONS_LABEL_CLASSES =
  'text-[0.9rem] tracking-[0.1px] text-cosci-idea-title-text';

// Reference: ul with 20px above the first link, then li+li margin-top 24px.
const IDEA_SECTIONS_LIST_CLASSES = 'mt-5 grid gap-6';

// Slightly smaller than the body so the longest link ("Tournament
// performance >") fits on one line without widening the rail.
const IDEA_SECTION_LINK_CLASSES =
  'block whitespace-nowrap text-[0.85rem] leading-6 font-medium ' +
  'text-cosci-blue no-underline';

// Detail section titles, in render order. Single source of truth so the
// section headings and the SectionsRail links can't drift apart.
const SECTIONS = {
  overview: 'Hypothesis overview',
  description: 'Description',
  provenance: 'Provenance & lineage',
  reviewSummary: 'Review summary',
  fullReview: 'Full review',
  tournament: 'Tournament performance',
  matchSummary: 'Match summary',
} as const;

// The rail links every section except "Match summary" (shown inline only).
const RAIL_SECTIONS: readonly string[] = [
  SECTIONS.overview,
  SECTIONS.description,
  SECTIONS.provenance,
  SECTIONS.reviewSummary,
  SECTIONS.fullReview,
  SECTIONS.tournament,
];

/**
 * Detail pane for one hypothesis: overview/description, review summary and
 * full critique, tournament win/loss record, and the most recent match's
 * outcome and rationale. Renders an empty-state placeholder when nothing is
 * selected (e.g. no hypotheses yet).
 */
export function HypothesisDetail({
  hypothesis,
  reviews,
  matches,
  claimEvidence = [],
}: {
  hypothesis: Hypothesis | null;
  // The run's full review/match/claim sets; the detail filters them down to
  // the hypothesis itself, so call sites just forward what they have.
  reviews: Review[];
  matches: MatchRow[];
  claimEvidence?: ClaimEvidenceRow[];
}) {
  // Memoized on their inputs so unrelated re-renders (e.g. SSE updates to
  // sibling collections) skip re-scanning the run's full review/match/claim
  // sets. Computed before the empty-state return to satisfy the rules of
  // hooks, hence the null guards.
  const review = useMemo(
    () => (hypothesis ? findHypothesisReview(hypothesis, reviews) : undefined),
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

  if (!hypothesis) {
    return (
      <section className={IDEA_DETAIL_EMPTY_CLASSES}>
        <Icon aria-hidden="true" name="format_list_numbered" />
        <p>Select a hypothesis to inspect the review and tournament details.</p>
      </section>
    );
  }

  return (
    <section
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

      <DetailSection title={SECTIONS.fullReview}>
        <p>{reviewCritiqueText(review)}</p>
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
function ClaimEvidenceDetail({claims}: {claims: ClaimEvidenceRow[]}) {
  const details = claims.map(c => ({
    claim: c,
    spans:
      c.label === 'contradicts'
        ? normalizeSpans(c.contradicting)
        : normalizeSpans(c.supporting),
  }));
  if (!details.length) return null;
  return (
    <div className="mt-1 flex flex-col gap-2">
      {details.map(({claim, spans}) => (
        <div key={claim.id} className="text-xs">
          <p>
            <span className="capitalize font-medium">
              {claim.label === 'insufficient'
                ? claim.claim_role === 'speculative'
                  ? 'Speculative — evidence insufficient'
                  : 'Unsupported categorical claim'
                : claim.label}
            </span>
            : {claim.claim}
          </p>
          {spans.length > 0 && (
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
          )}
        </div>
      ))}
    </div>
  );
}

// "Provenance & lineage" section body: where the hypothesis came from
// (Milestone 1 immutable-evolution lineage), its proximity cluster
// (Milestone 3), its safety status (Milestone 6), and a summary of its
// claim-evidence grounding (Milestone 5).
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

// "Match summary" section body: the optional outcome line, the debate depth,
// plus the rationale (or its placeholder). Props-only (no hooks).
function MatchSummaryContent({
  latestMatch,
}: {
  latestMatch: MatchRow | undefined;
}) {
  return (
    <>
      {latestMatch?.tier && (
        <p>
          <strong>Outcome:</strong>{' '}
          <span className="capitalize">{latestMatch.tier}</span>
        </p>
      )}
      {latestMatch && (
        <p>
          <strong>Debate depth:</strong>{' '}
          {debateDepthLabel(latestMatch.debate_turns)}
        </p>
      )}
      <p>{latestMatch?.rationale || 'No match rationale is available yet.'}</p>
    </>
  );
}

/** Anchor id for a detail section, shared by the section and its rail link. */
function sectionSlug(title: string): string {
  return title.toLowerCase().replaceAll(' ', '-');
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

/**
 * Right-hand jump-to-section links (desktop only, see
 * IDEA_SECTIONS_RAIL_CLASSES). Built from RAIL_SECTIONS, so it always mirrors
 * the actual DetailSection ids without needing to be kept in sync by hand.
 */
export function SectionsRail() {
  return (
    <aside className={IDEA_SECTIONS_RAIL_CLASSES} aria-label="Sections">
      <span className={IDEA_SECTIONS_LABEL_CLASSES}>Sections</span>
      <nav className={IDEA_SECTIONS_LIST_CLASSES}>
        {RAIL_SECTIONS.map(item => (
          <a
            key={item}
            href={`#${sectionSlug(item)}`}
            className={IDEA_SECTION_LINK_CLASSES}
            onClick={event => smoothSectionClick(event, sectionSlug(item))}
          >
            {item} &gt;
          </a>
        ))}
      </nav>
    </aside>
  );
}

// Intercepts a rail-link click to smooth-scroll to its section (with a 16px
// offset) instead of the browser's default instant-jump anchor navigation.
// Falls through to the default behavior when the target isn't found.
function smoothSectionClick(
  event: MouseEvent<HTMLAnchorElement>,
  sectionId: string,
) {
  const didScroll = smoothScrollToSection(
    sectionId,
    16,
    IDEA_SCROLL_PANE_SELECTOR,
  );
  if (!didScroll) return;
  event.preventDefault();
}

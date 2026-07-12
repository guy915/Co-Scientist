import type {MouseEvent, ReactNode} from 'react';
import type {
  ClaimEvidenceRow,
  Hypothesis,
  MatchRow,
  Review,
  SupportSpan,
} from '@/api/runs';
import {Icon} from '@/components/icon';
import {smoothScrollToSection} from '@/lib/smooth_scroll';

const IDEA_DETAIL_PANE_CLASSES =
  'idea-detail-pane grid min-h-0 min-w-0 flex-1 content-start gap-[1.35rem] ' +
  'overflow-x-hidden overflow-y-auto border-r-0 bg-transparent px-7 ' +
  'pt-[1.45rem] pb-14';

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

// The one review recorded for a hypothesis, if any. At most one review per
// hypothesis is expected, so find() is fine here.
function findHypothesisReview(
  hypothesis: Hypothesis,
  reviews: Review[],
): Review | undefined {
  return reviews.find(r => r.hypothesis_id === hypothesis.id);
}

// Most recent match involving a hypothesis on either side, used for the
// "Match summary" section's outcome/rationale.
function findLatestMatch(
  hypothesis: Hypothesis,
  matches: MatchRow[],
): MatchRow | undefined {
  return matches
    .filter(m => m.winner_id === hypothesis.id || m.loser_id === hypothesis.id)
    .sort((a, b) => b.created_at - a.created_at)[0];
}

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
  if (!hypothesis) {
    return (
      <section className={IDEA_DETAIL_EMPTY_CLASSES}>
        <Icon aria-hidden="true" name="format_list_numbered" />
        <p>Select a hypothesis to inspect the review and tournament details.</p>
      </section>
    );
  }

  const review = findHypothesisReview(hypothesis, reviews);
  const latestMatch = findLatestMatch(hypothesis, matches);
  const claims = claimEvidence.filter(c => c.hypothesis_id === hypothesis.id);

  return (
    <section
      className={IDEA_DETAIL_PANE_CLASSES}
      aria-label="Hypothesis detail"
    >
      <DetailSection title={SECTIONS.overview} level={2}>
        <p>{hypothesis.statement}</p>
      </DetailSection>

      <DetailSection title={SECTIONS.description} level={2}>
        <HypothesisDescriptionContent hypothesis={hypothesis} />
      </DetailSection>

      <DetailSection title={SECTIONS.provenance} level={2}>
        <HypothesisProvenanceContent hypothesis={hypothesis} claims={claims} />
      </DetailSection>

      <DetailSection title={SECTIONS.reviewSummary} level={2}>
        <p>{reviewSummaryText(review)}</p>
      </DetailSection>

      <DetailSection title={SECTIONS.fullReview} level={2}>
        <p>{reviewCritiqueText(review)}</p>
      </DetailSection>

      <DetailSection title={SECTIONS.tournament} level={2}>
        <p>{tournamentSummaryText(hypothesis)}</p>
      </DetailSection>

      <DetailSection title={SECTIONS.matchSummary} level={2}>
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

// Human-readable origin label for the agent/source that produced a hypothesis.
function originLabel(createdByAgent: string): string {
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
function claimEvidenceSummary(claims: ClaimEvidenceRow[]): string | null {
  if (!claims.length) return null;
  const counts = {supports: 0, contradicts: 0, insufficient: 0};
  for (const c of claims) {
    if (c.label === 'supports') counts.supports++;
    else if (c.label === 'contradicts') counts.contradicts++;
    else counts.insufficient++;
  }
  const parts = [`${claims.length} claim(s) assessed`];
  if (counts.supports) parts.push(`${counts.supports} supported`);
  if (counts.contradicts) parts.push(`${counts.contradicts} contradicted`);
  if (counts.insufficient) {
    parts.push(`${counts.insufficient} unsupported (speculative)`);
  }
  return parts.join(', ');
}

// A support span normalized for display: the exact quote plus (when known) a
// link to open its source. Tolerates legacy rows that stored a bare string.
interface NormalizedSpan {
  quote: string;
  url?: string;
}

function normalizeSpans(
  items: (SupportSpan | string)[] | undefined,
): NormalizedSpan[] {
  if (!items) return [];
  return items.map(item =>
    typeof item === 'string'
      ? {quote: item}
      : {quote: item.quote, url: item.url || undefined},
  );
}

// Renders the located evidence spans behind each supported/contradicted claim,
// so a reader can read the exact quote that grounds the verdict and open its
// source (Milestone 5 / P0.5). Insufficient (speculative) claims carry no span
// and are covered by the one-line summary above.
function ClaimEvidenceDetail({claims}: {claims: ClaimEvidenceRow[]}) {
  const grounded = claims
    .map(c => ({
      claim: c,
      spans:
        c.label === 'contradicts'
          ? normalizeSpans(c.contradicting)
          : normalizeSpans(c.supporting),
    }))
    .filter(({claim, spans}) => claim.label !== 'insufficient' && spans.length);
  if (!grounded.length) return null;
  return (
    <div className="mt-1 flex flex-col gap-2">
      {grounded.map(({claim, spans}) => (
        <div key={claim.id} className="text-xs">
          <p>
            <span className="capitalize font-medium">{claim.label}</span>:{' '}
            {claim.claim}
          </p>
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

// "Review summary" section text, falling back to a placeholder until the
// review node has run.
function reviewSummaryText(review: Review | undefined): string {
  return (
    review?.summary ||
    'Reviewer notes will appear after the review node completes.'
  );
}

// "Full review" section text, falling back to a placeholder until the review
// node has run.
function reviewCritiqueText(review: Review | undefined): string {
  return review?.critique || 'No full review has been recorded yet.';
}

// "Tournament performance" section text: the win/loss record and win rate,
// or a placeholder when no matches have been recorded yet.
function tournamentSummaryText(hypothesis: Hypothesis): string {
  const totalMatches = hypothesis.win_count + hypothesis.loss_count;
  if (!totalMatches) return 'No tournament matches have been recorded yet.';
  const winRate = Math.round((hypothesis.win_count / totalMatches) * 100);
  return `${hypothesis.win_count} wins and ${hypothesis.loss_count} losses across ${totalMatches} pairwise matches (${winRate}% win rate).`;
}

// Human-readable debate-depth label. 1 = single-turn comparison; anything
// greater is a multi-turn scientific debate (top-ranked matchups) — the
// median-Elo allocation from the Google system (SSR §4, §12).
function debateDepthLabel(turns: number | undefined): string {
  if (turns && turns > 1) {
    return `Multi-turn scientific debate (${turns} turns)`;
  }
  return 'Single-turn comparison';
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
// anchor target for SectionsRail's links and the deep-link hash. `level`
// selects h2 vs h3 for the heading's own semantic weight independent of the
// rail's flat link list.
function DetailSection({
  title,
  children,
  level = 3,
}: {
  title: string;
  children: ReactNode;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? 'h2' : 'h3';
  return (
    <section className={IDEA_DETAIL_SECTION_CLASSES} id={sectionSlug(title)}>
      <Heading>{title}</Heading>
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
  const didScroll = smoothScrollToSection(sectionId, 16);
  if (!didScroll) return;
  event.preventDefault();
}

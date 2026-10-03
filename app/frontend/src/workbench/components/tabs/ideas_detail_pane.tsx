import {useMemo, type MouseEvent, type ReactNode} from 'react';
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
  hasReviewDetail,
  NO_REVIEW_CRITIQUES_TEXT,
  parseReviewDetail,
  type ReviewDetail,
  reviewCritiqueText,
  reviewerLabel,
  claimEvidenceSummary,
  debateDepthLabel,
  normalizeSpans,
  parseDebateTranscript,
  type NormalizedSpan,
  originLabel,
  reviewSummaryText,
  tournamentSummaryText,
} from './ideas_detail_data';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import {HypothesisOutcomeSection} from './hypothesis_outcomes';

const IDEA_DETAIL_PANE_CLASSES =
  'idea-detail-pane grid min-h-0 min-w-0 flex-1 content-start gap-[1.35rem] ' +
  'overflow-x-hidden overflow-y-auto border-r-0 bg-transparent px-7 ' +
  // Below 1024 the columns stack (see IDEA_SPLIT_GRID_CLASSES), so the pane
  // grows with its content rather than scrolling inside a fixed height that
  // would trap the detail in a sliver. 700px is the separate phone gutter.
  'pt-[1.45rem] pb-14 max-[1023px]:flex-none ' +
  'max-[1023px]:overflow-y-visible max-[700px]:px-4';

// `text-th-muted-fg` is the named alias of --md-sys-color-on-surface-variant
// (see index.css); DESIGN.md keeps arbitrary token references out of
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
  allowRefinement?: boolean;
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
  allowRefinement,
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
      allowRefinement={allowRefinement}
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

/**
 * The detail pane's jump-to-section rail and the section vocabulary it and
 * the pane both build from.
 *
 * Split out of `ideas_detail_pane.tsx` to keep that module within the repo's
 * 500-line ceiling. The section titles live here rather than in the pane
 * because both sides need them and a second copy is how a rail link and its
 * heading drift apart.
 */

const IDEA_SECTIONS_RAIL_CLASSES =
  'idea-sections-rail m-5 min-w-0 min-w-[12.5rem] self-start ' +
  // Stacked, the rail is beside nothing and just pushes the detail down.
  'rounded-[10px] bg-cosci-panel p-5 max-[1023px]:hidden';

const IDEA_SECTIONS_LABEL_CLASSES =
  'text-[0.9rem] tracking-[0.1px] text-cosci-idea-title-text';

// Reference: ul with 20px above the first link, then li+li margin-top 24px.
const IDEA_SECTIONS_LIST_CLASSES = 'mt-5 grid gap-6';

// Slightly smaller than the body so the longest link ("Tournament
// performance >") fits on one line without widening the rail.
const IDEA_SECTION_LINK_CLASSES =
  'block whitespace-nowrap text-[0.85rem] leading-6 font-medium ' +
  'text-cosci-blue no-underline';

// The scroll pane a rail jump targets: the detail pane itself (which scrolls
// once the columns stack, below 1024px) or its `.cosci-report-scroll`
// ancestor (the desktop scroller, owned by run_detail.tsx), so the
// smooth-scroll lib carries no app-specific class knowledge.
const IDEA_SCROLL_PANE_SELECTOR = '.idea-detail-pane, .cosci-report-scroll';

// Detail section titles, in render order. Single source of truth so the
// section headings and the rail links can't drift apart.
export const SECTIONS = {
  overview: 'Hypothesis overview',
  description: 'Description',
  provenance: 'Provenance & lineage',
  outcomes: 'Empirical outcomes',
  reviewSummary: 'Review summary',
  reviewCritiques: 'Review critiques',
  tournament: 'Tournament performance',
  matchSummary: 'Match summary',
} as const;

// The rail links every section except "Match summary" (shown inline only).
const RAIL_SECTIONS: readonly string[] = [
  SECTIONS.overview,
  SECTIONS.description,
  SECTIONS.provenance,
  SECTIONS.outcomes,
  SECTIONS.reviewSummary,
  SECTIONS.reviewCritiques,
  SECTIONS.tournament,
];

/**
 * Anchor id for a detail section, shared by the section and its rail link.
 *
 * @param title The section's visible heading.
 * @returns The slug used as both the section id and the link's hash.
 */
export function sectionSlug(title: string): string {
  return title.toLowerCase().replaceAll(' ', '-');
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

/**
 * Right-hand jump-to-section links (hidden once the columns stack, see
 * IDEA_SECTIONS_RAIL_CLASSES). Built from RAIL_SECTIONS, so it always
 * mirrors the actual section ids without being kept in sync by hand.
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

/**
 * The detail pane's "Review critiques" section body, including each review
 * row's structured findings (R14-15/R14-22) alongside its free-text
 * critique.
 *
 * Split out of `ideas_detail_pane.tsx` to keep that module within the
 * repo's 500-line ceiling.
 */

// The full/recurrent review's display-only Go/No-Go framing (R14-15).
// Zero overlap with that row's critique text (correctness/quality/
// literature-grounding/justification/assumptions) -- a pure complement, so
// it renders unconditionally alongside the critique below it.
function VerdictLines({detail}: {detail: ReviewDetail}) {
  if (!detail.goNoGo && !detail.timeToVerdict) return null;
  return (
    <>
      {detail.goNoGo && (
        <p>
          <strong>Verdict: </strong>
          {detail.goNoGo}
        </p>
      )}
      {detail.timeToVerdict && (
        <p>
          <strong>Time to verdict: </strong>
          {detail.timeToVerdict}
        </p>
      )}
    </>
  );
}

// The simulation review's numbered failure points and decisive step
// (R14-22), matching report.markdown.hypothesis's bolded/numbered shape.
// The reviewer heading above this block already reads "Simulation review"
// (reviewerLabel), mirroring the markdown's own `#### Simulation review` --
// no second heading is needed here.
//
// This is the one reviewer type whose critique text already carries the
// same failure-point/decisive-step lines, flattened into that row's prose
// (report.markdown.hypothesis's critique formatter joins them with the
// row's "Simulated model"/step/robustness lines). The critique stays
// unedited below rather than having those lines stripped out of it: doing
// so would couple this component to that prose's exact label format, which
// is not a contract either side promises to hold still, and the critique is
// the only surface carrying the simulated model, per-step commentary, and
// robustness assessment this structured detail does not. The bolded list
// leads so a scanning reader sees the named failure points first, the way
// the report does.
function SimulationFindings({detail}: {detail: ReviewDetail}) {
  if (!detail.failurePoints.length && !detail.decisiveStep) return null;
  return (
    <>
      {detail.failurePoints.length > 0 && (
        <ol className="list-decimal pl-5">
          {detail.failurePoints.map((point, i) => (
            <li key={i}>
              <strong>Failure point:</strong> {point}
            </li>
          ))}
        </ol>
      )}
      {detail.decisiveStep && (
        <p>
          <strong>Decisive step: </strong>
          {detail.decisiveStep}
        </p>
      )}
    </>
  );
}

// One review row's structured findings, when its detail_json parsed to
// anything -- nothing for a row that predates the column, carries no
// structured content, or is malformed past recovery.
function ReviewFindings({review}: {review: Review}) {
  const detail = parseReviewDetail(review);
  if (!hasReviewDetail(detail)) return null;
  return (
    <div className="mb-1">
      <VerdictLines detail={detail} />
      <SimulationFindings detail={detail} />
    </div>
  );
}

// "Review critiques" section body: every review row recorded for the idea,
// each under its reviewer's own heading, so the initial peer review, the
// deep verification, and the full/simulation/recurrent results stay
// visibly distinct findings (audit E1/D13) instead of one collapsed block.
// A row carrying structured detail_json (R14-15/R14-22) surfaces it above
// the free-text critique -- see ReviewFindings/SimulationFindings for why
// both render rather than one replacing the other. Props-only (no hooks).
export function ReviewCritiquesContent({reviews}: {reviews: Review[]}) {
  if (!reviews.length) {
    return <p>{NO_REVIEW_CRITIQUES_TEXT}</p>;
  }
  return (
    <>
      {reviews.map(item => (
        <div key={item.id} className="mb-3 last:mb-0">
          <h3>{reviewerLabel(item.reviewer_agent)}</h3>
          <ReviewFindings review={item} />
          <p>{reviewCritiqueText(item)}</p>
        </div>
      ))}
    </>
  );
}

// Shared by the populated/empty pane and each rank row's aria-controls link.
export const DETAIL_PANE_ID = 'hypothesis-detail-pane';

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

interface DetailSectionsProps {
  paneClasses: string;
  hypothesis: Hypothesis;
  runId?: string;
  allowRefinement?: boolean;
  isDemo?: boolean;
  review: Review | undefined;
  allReviews: Review[];
  matchHistory: MatchRow[];
  claims: ClaimEvidenceRow[];
  outcomes: HypothesisOutcome[];
  outcomesLoading?: boolean;
  outcomesError?: string | null;
  onRefreshOutcomes?: () => Promise<void> | void;
}

// The ordered detail sections for a selected hypothesis. Props-only (no
// hooks), so the parent keeps every hook above its empty-state return.
export function HypothesisDetailSections({
  paneClasses,
  hypothesis,
  runId,
  allowRefinement,
  isDemo,
  review,
  allReviews,
  matchHistory,
  claims,
  outcomes,
  outcomesLoading,
  outcomesError,
  onRefreshOutcomes,
}: DetailSectionsProps) {
  return (
    <section
      id={DETAIL_PANE_ID}
      className={paneClasses}
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
      {runId && onRefreshOutcomes && (
        <DetailSection title={SECTIONS.outcomes}>
          <HypothesisOutcomeSection
            runId={runId}
            allowRefinement={allowRefinement}
            hypothesis={hypothesis}
            readOnly={isDemo}
            outcomes={outcomes}
            loading={outcomesLoading}
            error={outcomesError}
            onRefresh={onRefreshOutcomes}
          />
        </DetailSection>
      )}
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
        <MatchSummaryContent
          hypothesisId={hypothesis.id}
          matches={matchHistory}
        />
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
                className="not-italic underline pointer-coarse:inline-block pointer-coarse:py-2"
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

// "Match summary" section body: each persisted result and its optional
// turn-by-turn transcript, ordered newest first. Props-only (no hooks).
function MatchSummaryContent({
  hypothesisId,
  matches,
}: {
  hypothesisId: string;
  matches: MatchRow[];
}) {
  if (!matches.length) {
    return <p>No match rationale is available yet.</p>;
  }
  return (
    <>
      <h3>Match history</h3>
      <ol className="mt-2 flex flex-col gap-4">
        {matches.map(match => (
          <MatchHistoryItem
            key={match.id}
            hypothesisId={hypothesisId}
            match={match}
          />
        ))}
      </ol>
    </>
  );
}

function MatchHistoryItem({
  hypothesisId,
  match,
}: {
  hypothesisId: string;
  match: MatchRow;
}) {
  const transcript = parseDebateTranscript(match.debate_transcript);

  return (
    <li className="grid gap-1 border-l-2 border-th-outline-variant pl-3">
      <p>{matchResult(match, hypothesisId)}</p>
      <p>{matchIteration(match)}</p>
      <p>
        <strong>Elo change:</strong>{' '}
        {formatEloChange(matchEloChange(match, hypothesisId))}
      </p>
      <p>
        <strong>Debate depth:</strong> {debateDepthLabel(match.debate_turns)}
      </p>
      <p>{match.rationale || 'No match rationale was recorded.'}</p>
      {transcript && (
        <MatchTranscriptDisclosure
          transcript={transcript}
          selectedSide={selectedTranscriptSide(
            match,
            hypothesisId,
            transcript.verdict,
          )}
        />
      )}
    </li>
  );
}

function matchResult(match: MatchRow, hypothesisId: string): string {
  const won = match.winner_id === hypothesisId;
  return `${won ? 'Win' : 'Loss'} against ${won ? match.loser_id : match.winner_id}`;
}

function matchIteration(match: MatchRow): string {
  return `Iteration ${match.iteration}${match.tier ? ` · ${match.tier}` : ''}`;
}

function matchEloChange(match: MatchRow, hypothesisId: string): number {
  return match.winner_id === hypothesisId
    ? match.winner_elo_after - match.winner_elo_before
    : match.loser_elo_after - match.loser_elo_before;
}

function formatEloChange(change: number): string {
  return `${change > 0 ? '+' : ''}${change}`;
}

function selectedTranscriptSide(
  match: MatchRow,
  hypothesisId: string,
  verdict: '1' | '2',
): '1' | '2' {
  return (verdict === '1') === (match.winner_id === hypothesisId) ? '1' : '2';
}

function MatchTranscriptDisclosure({
  transcript,
  selectedSide,
}: {
  transcript: NonNullable<ReturnType<typeof parseDebateTranscript>>;
  selectedSide: '1' | '2';
}) {
  if (!transcript.turns.length) return null;
  return (
    <details>
      <summary>Debate transcript ({transcript.turns.length} turns)</summary>
      <ol className="mt-2 flex flex-col gap-2">
        {transcript.turns.map(turn => {
          const selectedWasPresentedFirst = turn.first === selectedSide;
          const selectedWasFavored = turn.favored === selectedSide;
          return (
            <li key={turn.turn}>
              <p>
                <strong>Turn {turn.turn}:</strong> selected hypothesis was
                presented as Hypothesis {selectedWasPresentedFirst ? '1' : '2'};
                this turn favored {selectedWasFavored ? 'it' : 'the opponent'}.
              </p>
              <p>{turn.text}</p>
            </li>
          );
        })}
      </ol>
    </details>
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

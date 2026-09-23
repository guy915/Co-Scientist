import type {ReactNode} from 'react';
import type {
  ClaimEvidenceRow,
  Hypothesis,
  HypothesisOutcome,
  MatchRow,
  Review,
} from '@/api/runs';
import {
  claimEvidenceSummary,
  debateDepthLabel,
  normalizeSpans,
  parseDebateTranscript,
  type NormalizedSpan,
  originLabel,
  reviewSummaryText,
  tournamentSummaryText,
} from './ideas_detail_data';
import {SECTIONS, sectionSlug} from './ideas_detail_rail';
import {ReviewCritiquesContent} from './ideas_detail_review_findings';
import {HypothesisOutcomeSection} from './hypothesis_outcomes';

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

import {useMemo} from 'react';
import {
  type Hypothesis,
  type AgentInsights,
  type MatchRow,
  type Report,
  type ReportPayload,
  type ResearchOverview,
  type RunWithSummary,
} from '@/api/runs';
import {formatDurationPhrase} from '@/lib/duration';
import {sortByEloDesc} from '@/lib/hypotheses';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
  REPORT_SECTION_LIST_ITEM_CLASSES,
  REPORT_SECTION_LIST_META_CLASSES,
  ReportDocument,
} from './run_detail_document';

const REPORT_LEAD_STAT_CLASSES =
  'cosci-overview-lead-stat mt-1 mb-4 text-cosci-fg';

// Report-backed overview stats, falling back to the live rows while a run is
// still in flight and has no persisted report yet.
function overviewReportStats(
  report: Report | null,
  hypotheses: Hypothesis[],
  matches: MatchRow[],
): {
  overview: ResearchOverview | undefined;
  leaderboard: ReportPayload['leaderboard'];
  ideaCount: number;
  matchCount: number;
} {
  if (!report) {
    return {
      overview: undefined,
      leaderboard: [],
      ideaCount: hypotheses.length,
      matchCount: matches.length,
    };
  }
  const {payload} = report;
  return {
    overview: payload.research_overview,
    leaderboard: payload.leaderboard,
    ideaCount: payload.hypothesis_count ?? hypotheses.length,
    matchCount: payload.match_count ?? matches.length,
  };
}

// Top ideas by Elo, normalized to one shape from whichever source is
// available: the persisted report leaderboard, else the live hypotheses.
function winningIdeasItems(
  leaderboard: ReportPayload['leaderboard'],
  hypotheses: Hypothesis[],
): {id: string; title: string; elo: number}[] {
  if (leaderboard.length) {
    return leaderboard
      .slice(0, 5)
      .map(item => ({id: item.id, title: item.title, elo: item.elo}));
  }
  return sortByEloDesc(hypotheses)
    .slice(0, 5)
    .map(h => ({id: h.id, title: h.title, elo: h.elo_rating}));
}

// Derives the lead-stat sentence and the top-5 "Winning ideas" list for the
// research-overview tab, memoized off the same report-or-live stats the
// caller already resolved via overviewReportStats.
function useResearchOverviewDerived({
  run,
  leaderboard,
  hypotheses,
  ideaCount,
  matchCount,
}: {
  run: RunWithSummary | null;
  leaderboard: ReportPayload['leaderboard'];
  hypotheses: Hypothesis[];
  ideaCount: number;
  matchCount: number;
}) {
  const leadStat = useMemo(
    () =>
      researchOverviewLeadStat({
        run,
        leaderboard,
        hypotheses,
        ideaCount,
        matchCount,
      }),
    [run, leaderboard, hypotheses, ideaCount, matchCount],
  );

  const winningIdeas = useMemo(
    () => winningIdeasItems(leaderboard, hypotheses),
    [leaderboard, hypotheses],
  );

  return {leadStat, winningIdeas};
}

/**
 * Summary tab: Agent Insights plus the synthesized report
 * directions, specific aims), a lead-stat sentence, a top-5 leaderboard, and
 * a tournament-match count. Falls back to live hypotheses/matches when no
 * persisted report exists yet (run still in progress).
 */
export function ResearchOverviewView({
  run,
  report,
  hypotheses,
  matches,
}: {
  run: RunWithSummary | null;
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
}) {
  const {overview, leaderboard, ideaCount, matchCount} = overviewReportStats(
    report,
    hypotheses,
    matches,
  );
  const {leadStat, winningIdeas} = useResearchOverviewDerived({
    run,
    leaderboard,
    hypotheses,
    ideaCount,
    matchCount,
  });

  return (
    <ReportDocument title="Summary">
      {leadStat ? <p className={REPORT_LEAD_STAT_CLASSES}>{leadStat}</p> : null}
      <AgentInsightsSection insights={report?.payload.agent_insights} />
      <OverviewSummary overview={overview} />
      <ResearchDirectionsSection overview={overview} />
      <SpecificAimsSection overview={overview} />
      <WinningIdeasSection items={winningIdeas} />
      <TournamentSummarySection matches={matches} />
    </ReportDocument>
  );
}

// The run-wide Agent Insights block exposes findings and uncertainty without
// leaking private reasoning traces.
function AgentInsightsSection({
  insights,
}: {
  insights: AgentInsights | undefined;
}) {
  if (!insights) return null;
  const sections: [string, string[]][] = [
    ['Key findings', insights.key_findings],
    ['Uncertainties', insights.uncertainties],
    ['Contradictions', insights.contradictions],
    ['Recommended directions', insights.recommended_directions],
    ['Next experiments', insights.next_experiments],
  ];
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Agent Insights</h3>
      {sections.map(([title, values]) =>
        values.length ? (
          <div key={title}>
            <h4 className={REPORT_H4_CLASSES}>{title}</h4>
            <ul className={REPORT_LIST_CLASSES}>
              {values.map(value => (
                <li key={value}>{value}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </section>
  );
}

// Overview summary sentence, or the pre-synthesis placeholder.
function OverviewSummary({overview}: {overview: ResearchOverview | undefined}) {
  const summary = overview?.overview?.summary;
  if (summary) return <p>{summary}</p>;
  return (
    <p>
      The research overview appears after Co-Scientist finishes the final
      synthesis step.
    </p>
  );
}

// "Research directions" section of the research-overview report; renders
// nothing until the report has research directions.
function ResearchDirectionsSection({
  overview,
}: {
  overview: ResearchOverview | undefined;
}) {
  const directions = overview?.overview?.research_directions;
  if (!directions?.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Research directions</h3>
      {directions.map(direction => (
        <div key={direction.title}>
          <h4 className={REPORT_H4_CLASSES}>{direction.title}</h4>
          <p>{direction.importance}</p>
          {direction.suggested_experiments.length ? (
            <ul className={REPORT_LIST_CLASSES}>
              {direction.suggested_experiments.map(experiment => (
                <li key={experiment}>{experiment}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </section>
  );
}

// Renders `text` as a paragraph when present, else nothing — used for the
// optional introduction/impact copy around a specific-aims list.
function OptionalParagraph({text}: {text: string | undefined}) {
  if (!text) return null;
  return <p>{text}</p>;
}

// "Specific aims" section of the research-overview report; renders nothing
// until the report has specific aims.
function SpecificAimsSection({
  overview,
}: {
  overview: ResearchOverview | undefined;
}) {
  const specificAims = overview?.nih_specific_aims;
  if (!specificAims?.aims?.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Specific aims</h3>
      <OptionalParagraph text={specificAims.introduction} />
      {specificAims.aims.map(aim => (
        <div key={aim.aim}>
          <h4 className={REPORT_H4_CLASSES}>{aim.aim}</h4>
          <p>{aim.rationale}</p>
          <p>{aim.approach}</p>
        </div>
      ))}
      <OptionalParagraph text={specificAims.impact} />
    </section>
  );
}

// "Winning ideas" section of the research-overview report: top hypotheses by
// Elo, normalized to one shape by the caller; renders nothing when empty.
function WinningIdeasSection({
  items,
}: {
  items: {id: string; title: string; elo: number}[];
}) {
  if (!items.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Winning ideas</h3>
      <ol className={REPORT_LIST_CLASSES}>
        {items.map(item => (
          <li className={REPORT_SECTION_LIST_ITEM_CLASSES} key={item.id}>
            <strong>{item.title}</strong>
            <span className={REPORT_SECTION_LIST_META_CLASSES}>
              Elo rating: {item.elo}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

// "Tournament summary" section of the research-overview report.
function TournamentSummarySection({matches}: {matches: MatchRow[]}) {
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Tournament summary</h3>
      <p>
        {matches.length
          ? `${matches.length} tournament matches have been recorded for this run.`
          : 'Tournament matches appear here once ranking begins.'}
      </p>
    </section>
  );
}

// "N thing was/were" pluralization for the lead-stat sentence's clauses.
function pluralPhrase(count: number, singular: string, plural: string): string {
  return count === 1 ? singular : plural;
}

/**
 * Builds the reference's lead stat sentence, e.g. "A total of 133 ideas were
 * explored over 3 hours with the highest Elo rating of 1735 points and a total
 * of 1360 matches were played." Clauses whose data is unknown are omitted, and
 * an empty string is returned when there is nothing meaningful to report yet.
 */
function researchOverviewLeadStat({
  run,
  leaderboard,
  hypotheses,
  ideaCount,
  matchCount,
}: {
  run: RunWithSummary | null;
  leaderboard: {elo: number}[];
  hypotheses: Hypothesis[];
  ideaCount: number;
  matchCount: number;
}): string {
  if (!ideaCount) return '';

  const duration = runDurationPhrase(run);
  const highestElo = Math.max(
    0,
    ...leaderboard.map(item => item.elo),
    ...hypotheses.map(hypothesis => hypothesis.elo_rating),
  );

  const clauses = [
    duration ? ` over ${duration}` : '',
    highestElo > 0
      ? ` with the highest Elo rating of ${highestElo} points`
      : '',
    matchCount > 0
      ? ` and a total of ${matchCount} ${pluralPhrase(matchCount, 'match was', 'matches were')} played`
      : '',
  ];
  const ideaLabel = pluralPhrase(ideaCount, 'idea was', 'ideas were');
  const sentence =
    `A total of ${ideaCount} ${ideaLabel} explored` +
    clauses.filter(Boolean).join('');
  return `${sentence}.`;
}

// completed_at/created_at as a validated pair (both present), or null when
// either timestamp is missing.
function runTimestampPair(
  run: RunWithSummary | null,
): {completedAt: number; createdAt: number} | null {
  if (!run?.completed_at || !run.created_at) return null;
  return {completedAt: run.completed_at, createdAt: run.created_at};
}

/**
 * Formats a run's wall-clock duration (creation to completion) as a rounded
 * human phrase, e.g. "3 hours" or "12 minutes". Returns an empty string when
 * the run has not completed or the timestamps are unusable.
 */
function runDurationPhrase(run: RunWithSummary | null): string {
  const pair = runTimestampPair(run);
  if (!pair) return '';
  const seconds = pair.completedAt - pair.createdAt;
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  return formatDurationPhrase(seconds);
}

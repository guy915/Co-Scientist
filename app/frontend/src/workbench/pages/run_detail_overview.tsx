import {useMemo} from 'react';
import {
  type Hypothesis,
  type MatchRow,
  type Report,
  type ReportPayload,
  type ResearchOverview,
  type RunWithSummary,
} from '@/api/runs';
import {formatDurationPhrase} from '@/lib/duration';
import {sortByEloDesc} from '@/lib/hypotheses';
import {readableText} from '@/lib/text';
import {
  AgentInsightsSection,
  DegradedSectionNotice,
  META_REVIEW_SCHEMA,
  RESEARCH_OVERVIEW_SCHEMA,
  RetrievalDegradationNotice,
  sectionDegraded,
} from './run_detail_insights';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
  REPORT_SECTION_LIST_ITEM_CLASSES,
  REPORT_SECTION_LIST_META_CLASSES,
  ReportDocument,
} from './run_detail_document';
import {SpecificAimsSection} from './run_detail_overview_aims';
import {ResearchDirectionsSection} from './run_detail_overview_directions';

const STAT_GRID_CLASSES =
  'grid grid-cols-4 gap-3 max-[900px]:grid-cols-2 max-[520px]:grid-cols-1';

const REPORT_LEAD_STAT_CLASSES =
  'cosci-overview-lead-stat mt-1 mb-4 text-cosci-fg';

// The stand-in for a report that has no leaderboard yet. Module scope, not a
// fresh `[]` per call: this value is a useMemo dependency downstream, and a
// new array identity on every render defeated both of those memos for any run
// without a persisted report -- they recomputed on all 6 of 6 renders instead
// of 1.
const NO_LEADERBOARD: ReportPayload['leaderboard'] = [];

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
      leaderboard: NO_LEADERBOARD,
      ideaCount: hypotheses.length,
      matchCount: matches.length,
    };
  }
  const {payload} = report;
  return {
    overview: payload.research_overview,
    leaderboard: payload.leaderboard,
    // Every idea explored, not the released subset. `hypothesis_count` is
    // the post-gate count, so reading it here made a run that explored 22
    // ideas and released 2 announce "A total of 2 ideas were explored"
    // above its own list of 22. Reports predating the field fall back to
    // the live rows, which are also the full set.
    ideaCount: payload.idea_count ?? hypotheses.length,
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
      <RetrievalDegradationNotice report={report} />
      <SummaryStats payload={report?.payload} />
      <AgentInsightsSection
        insights={report?.payload.agent_insights}
        degraded={sectionDegraded(report, META_REVIEW_SCHEMA)}
      />
      <OverviewSummary
        overview={overview}
        degraded={sectionDegraded(report, RESEARCH_OVERVIEW_SCHEMA)}
      />
      <ResearchDirectionsSection overview={overview} />
      <SpecificAimsSection overview={overview} />
      <ResearchContactsSection overview={overview} />
      <WinningIdeasSection items={winningIdeas} />
      <TournamentSummarySection matches={matches} />
    </ReportDocument>
  );
}

// One idea-bucket's entry count, defaulted to 0 when the report has no
// bucket breakdown yet.
function bucketCount(
  payload: ReportPayload,
  key: 'high_potential' | 'non_viable',
): number {
  return payload.idea_buckets?.[key].length ?? 0;
}

// "Verified ideas" is the count of released ideas with an evidence-supported
// claim — the same fact the per-idea "Unverified" badge shows, so the two
// come from one server-side derivation. It used to repeat the High Potential
// count, which made it a duplicate of the tile beside it and let a run report
// two verified ideas while badging every idea in the list unverified.
function reportStats(payload: ReportPayload): (readonly [string, number])[] {
  return [
    ['High Potential', bucketCount(payload, 'high_potential')],
    ['Non-Viable', bucketCount(payload, 'non_viable')],
    ['Verified ideas', payload.verified_count ?? 0],
    ['Sources Analyzed', payload.evidence_count ?? 0],
  ] as const;
}

function SummaryStats({payload}: {payload: ReportPayload | undefined}) {
  if (!payload) return null;
  const stats = reportStats(payload);
  return (
    <dl className={STAT_GRID_CLASSES}>
      {stats.map(([label, value]) => (
        <div key={label} className="rounded-md bg-cosci-panel p-4">
          <dt className="text-sm text-cosci-muted">{label}</dt>
          <dd className="mt-1 text-2xl font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

// Suggestions are restricted by the engine to authors of analyzed sources.
function ResearchContactsSection({
  overview,
}: {
  overview: ResearchOverview | undefined;
}) {
  const contacts = overview?.research_contacts;
  if (!contacts?.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Research contacts</h3>
      <p>
        Relevant authors identified from the literature analyzed in this run.
      </p>
      {contacts.map(contact => {
        // MO-7: ties the contact back to the direction that surfaced them.
        // research_overview_contacts.py:151 degrades a missing field to ""
        // (like a report persisted before it existed), so an empty value
        // renders no label rather than a label with nothing after it.
        const direction = readableText(contact.research_direction);
        return (
          <div key={contact.candidate_id}>
            <h4 className={REPORT_H4_CLASSES}>{readableText(contact.name)}</h4>
            {direction ? (
              <p>
                <strong>Research direction: </strong>
                {direction}
              </p>
            ) : null}
            <p>{readableText(contact.expertise)}</p>
            {/* R14-16: Justification: is the one label consistent across
                all 14 published research contacts that carry it. */}
            <p>
              <strong>Justification: </strong>
              {readableText(contact.justification)}
            </p>
            {/* R14-16: the second, evidence-citing field's published label
                varies freely; "Supporting article" is this schema's own
                fixed name for it -- always exactly one grounded paper
                (source_title/source_url), never free citation prose. */}
            {contact.source_url ? (
              <a
                className="text-th-primary underline"
                href={contact.source_url}
                rel="noreferrer"
                target="_blank"
              >
                Supporting article: {readableText(contact.source_title)}
              </a>
            ) : (
              <p>Supporting article: {readableText(contact.source_title)}</p>
            )}
          </div>
        );
      })}
    </section>
  );
}

// The overview's summary sentence, empty when there is none yet.
function overviewSummaryText(overview: ResearchOverview | undefined): string {
  return readableText(overview?.overview?.summary);
}

// Overview summary sentence, or the pre-synthesis placeholder. When the run's
// report says the research overview degraded (L7), a blank summary is
// labelled as a generation failure rather than left as an in-flight promise.
function OverviewSummary({
  overview,
  degraded = false,
}: {
  overview: ResearchOverview | undefined;
  degraded?: boolean;
}) {
  const summary = overviewSummaryText(overview);
  if (summary) return <p>{summary}</p>;
  if (degraded) return <DegradedSectionNotice />;
  return (
    <p>
      The research overview appears after Co-Scientist finishes the final
      synthesis step.
    </p>
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
          ? `${matches.length} tournament matches have been recorded ` +
            'for this run.'
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
      ? ` and a total of ${matchCount} ` +
        `${pluralPhrase(matchCount, 'match was', 'matches were')} played`
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

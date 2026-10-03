import {useMemo} from 'react';
import type {
  Hypothesis,
  HypothesisOutcome,
  MatchRow,
  Report,
  ReportPayload,
  ResearchOverview,
  RunWithSummary,
  AgentInsights,
  RecommendedDirection,
} from '@/api/runs';
import {
  formatDurationPhrase,
  readableText,
  isRecord,
  readableTextList,
} from '@/lib/text';
import {sortByEloDesc} from '@/lib/hypotheses';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
  REPORT_SECTION_LIST_ITEM_CLASSES,
  REPORT_SECTION_LIST_META_CLASSES,
  ReportDocument,
} from './run_detail_shell';
import {RunOutcomesReport} from '../components/tabs/hypothesis_outcomes';

const STAT_GRID_CLASSES = 'grid grid-cols-4 gap-3 max-[900px]:grid-cols-2';

const REPORT_LEAD_STAT_CLASSES =
  'cosci-overview-lead-stat mt-1 mb-4 text-cosci-fg';

// The stand-in for a report that has no leaderboard yet. Module scope, not a
// fresh `[]` per call: this value is a useMemo dependency downstream, and a
// new array identity on every render defeated both of those memos for any run
// without a persisted report -- they recomputed on all 6 of 6 renders instead
// of 1.
const NO_LEADERBOARD: NonNullable<ReportPayload['leaderboard']> = [];

// Report-backed overview stats, falling back to the live rows while a run is
// still in flight and has no persisted report yet.
function overviewReportStats(
  report: Report | null,
  hypotheses: Hypothesis[],
  matches: MatchRow[],
): {
  overview: ResearchOverview | undefined;
  leaderboard: NonNullable<ReportPayload['leaderboard']>;
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
    leaderboard: payload.leaderboard ?? NO_LEADERBOARD,
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
  leaderboard: NonNullable<ReportPayload['leaderboard']>,
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
  leaderboard: NonNullable<ReportPayload['leaderboard']>;
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
  outcomes,
  outcomesLoading,
  outcomesError,
  onRefreshOutcomes,
}: {
  run: RunWithSummary | null;
  report: Report | null;
  hypotheses: Hypothesis[];
  matches: MatchRow[];
  outcomes?: HypothesisOutcome[];
  outcomesLoading?: boolean;
  outcomesError?: string | null;
  onRefreshOutcomes?: () => Promise<void> | void;
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
    <>
      <ReportDocument title="Summary">
        {leadStat ? (
          <p className={REPORT_LEAD_STAT_CLASSES}>{leadStat}</p>
        ) : null}
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
      <RunOutcomesReport
        outcomes={outcomes}
        hypotheses={hypotheses}
        loading={outcomesLoading}
        error={outcomesError}
        onRefresh={onRefreshOutcomes}
        readOnly={run?.is_demo}
      />
    </>
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

// The "Specific aims" section of the research overview.

// Renders nothing until the report has specific aims.
export function SpecificAimsSection({
  overview,
}: {
  overview: ResearchOverview | undefined;
}) {
  const specificAims = overview?.nih_specific_aims;
  if (!specificAims?.aims?.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Specific aims</h3>
      {AIMS_PREAMBLE_FIELDS.map(([key, heading]) => (
        <LabeledBlock
          key={key}
          heading={heading}
          text={readableText(specificAims[key])}
        />
      ))}
      {specificAims.aims.map((aim, index) => (
        <SpecificAim key={index} aim={aim} number={index + 1} />
      ))}
      {AIMS_CLOSING_FIELDS.map(([key, heading]) => (
        <LabeledBlock
          key={key}
          heading={heading}
          text={readableText(specificAims[key])}
        />
      ))}
    </section>
  );
}

// The page blocks Google's published Specific Aims exemplars print, plus
// the introduction/impact pair reports stored before that vocabulary
// landed still carry. The legacy introduction keeps its unheaded
// paragraph so an old report reads exactly as it did.
const AIMS_PREAMBLE_FIELDS = [
  ['introduction', ''],
  ['disease_description', 'Disease description'],
  ['unmet_need', 'Unmet need'],
  ['proposed_solution', 'Proposed solution'],
] as const;
const AIMS_CLOSING_FIELDS = [
  ['pilot_evaluation', 'Pilot evaluation'],
  ['impact', ''],
] as const;
// Per-aim body fields, each labelled; new spelling first, same order and
// labels as report/markdown/overview.py's _AIM_BODY_FIELDS. Only one
// spelling of each pair is ever present, so the whole list renders in
// order.
//
// F4/OVERVIEW-AIMS-VOCABULARY-001: the heading is now the aim's number
// (matching every published exemplar), and the goal moves into this
// list as a labelled body field rather than standing in for the
// heading text. Section heading ("Specific aims", h3) and per-aim
// heading ("Specific Aims N", h4) share the phrase but not the heading
// role, so a heading-role-scoped selector (used by the e2e spec and the
// section test below) still finds exactly one of each rather than a
// strict-mode collision.
const AIM_BODY_FIELDS = [
  ['overarching_goal', 'Overarching goal'],
  ['aim', 'Aim'],
  ['hypothesis', 'Hypothesis'],
  ['reasoning', 'Reasoning'],
  ['rationale', 'Rationale'],
  ['approach', 'Approach'],
] as const;

// One headed block of the aims page, or a bare paragraph when the field
// predates the headings; renders nothing when the field is empty.
function LabeledBlock({heading, text}: {heading: string; text: string}) {
  if (!text) return null;
  if (!heading) return <p>{text}</p>;
  return (
    <div>
      <h4 className={REPORT_H4_CLASSES}>{heading}</h4>
      <p>{text}</p>
    </div>
  );
}

// One specific-aim entry, coercing each field so a malformed (object or
// JSON-string) value renders as readable text rather than raw JSON.
//
// F4/OVERVIEW-AIMS-VOCABULARY-001: every published exemplar heads an aim
// by its number ("Specific Aims N") and prints its overarching goal as a
// labelled body field beneath it, not as the heading text -- mirroring
// report/markdown/overview.py's _render_nih_aim exactly.
function SpecificAim({aim, number}: {aim: unknown; number: number}) {
  const record = isRecord(aim) ? aim : {};
  return (
    <div>
      <h4 className={REPORT_H4_CLASSES}>Specific Aims {number}</h4>
      {AIM_BODY_FIELDS.map(([key, label]) => {
        const text = readableText(record[key]);
        if (!text) return null;
        return (
          <p key={key}>
            <strong>{label}: </strong>
            {text}
          </p>
        );
      })}
    </div>
  );
}

// The "Research directions" section of the research overview.

interface SubTopicEntry {
  title: string;
  why: string;
  what: string;
  // F7: the exemplar's own "Example idea" block, between the topic's
  // reasoning and its questions. Empty on a sub-topic from a report
  // persisted before it existed.
  exampleIdea: string;
  questions: string[];
}

interface DirectionEntry {
  title: string;
  importance: string;
  // MO-12: the "what is already known" slot ALS's exemplar names "Recent
  // Findings". Absent on a direction from a report persisted before it
  // existed.
  recentFindings: string;
  experiments: string[];
  // MO-1: the nested sub-topic layer both exemplars develop "what to
  // research" as. Absent on a direction from a report persisted before it
  // existed.
  subTopics: SubTopicEntry[];
}

// Coerce one raw sub-topic into readable fields, tolerating the same
// json_object-mode malformations toDirectionEntry guards against.
function toSubTopicEntry(raw: unknown): SubTopicEntry {
  const record = isRecord(raw) ? raw : {};
  return {
    title: readableText(record.title),
    why: readableText(record.why),
    what: readableText(record.what),
    exampleIdea: readableText(record.example_idea),
    questions: readableTextList(record.specific_questions),
  };
}

// Normalize a direction's sub-topics into renderable entries, dropping any
// that carry no content after coercion.
function subTopicEntries(raw: unknown): SubTopicEntry[] {
  const list = Array.isArray(raw) ? raw : [];
  return list
    .map(toSubTopicEntry)
    .filter(
      e => e.title || e.why || e.what || e.exampleIdea || e.questions.length,
    );
}

// Coerce one raw research-direction into readable fields, tolerating the
// json_object-mode malformations (a string field arriving as an object, or as
// serialized JSON) that would otherwise render as raw JSON.
function toDirectionEntry(raw: unknown): DirectionEntry {
  const record = isRecord(raw) ? raw : {};
  return {
    title: readableText(record.title),
    importance: readableText(record.importance),
    recentFindings: readableText(record.recent_findings),
    experiments: readableTextList(record.suggested_experiments),
    subTopics: subTopicEntries(record.sub_topics),
  };
}

// Normalize the overview's research directions into renderable entries,
// dropping any that carry no content after coercion.
function directionEntries(
  overview: ResearchOverview | undefined,
): DirectionEntry[] {
  const raw = overview?.overview?.research_directions as unknown;
  const list = Array.isArray(raw) ? raw : [];
  return list
    .map(toDirectionEntry)
    .filter(
      e =>
        e.title ||
        e.importance ||
        e.recentFindings ||
        e.experiments.length ||
        e.subTopics.length,
    );
}

// MO-12: both published exemplars front-load a named preview list ahead of
// the full per-direction detail that follows (report.markdown.overview's
// _render_directions_preview). Titles only, no new content -- naming each
// direction rather than repeating its prose avoids duplicating the
// paragraphs the full detail below already carries.
//
// A "preview" of a single named direction duplicates it rather than
// orienting the reader, so the gate matches the markdown renderer's own:
// fewer than two named directions renders nothing here.
function DirectionsPreview({directions}: {directions: DirectionEntry[]}) {
  const titles = directions.map(d => d.title).filter(Boolean);
  if (titles.length < 2) return null;
  return (
    <>
      <p>We will be focusing on these research directions:</p>
      <ul className={REPORT_LIST_CLASSES}>
        {titles.map((title, i) => (
          <li key={`${title}-${i}`}>{title}</li>
        ))}
      </ul>
    </>
  );
}

// A sub-topic's labelled prose blocks, in the order the published
// exemplar prints them: the topic's reasoning, what it covers, then one
// worked example, ahead of its specific questions.
const SUB_TOPIC_BODY_FIELDS = [
  ['why', 'Why'],
  ['what', 'What'],
  ['exampleIdea', 'Example idea'],
] as const;

// One labelled sub-topic line, or nothing when the field is empty.
function SubTopicLine({label, text}: {label: string; text: string}) {
  if (!text) return null;
  return (
    <p>
      <strong>{label}: </strong>
      {text}
    </p>
  );
}

// One named sub-topic entry, or nothing when coercion left it empty.
function SubTopicItem({subTopic}: {subTopic: SubTopicEntry}) {
  return (
    <div>
      {subTopic.title ? (
        <p>
          <strong>{subTopic.title}</strong>
        </p>
      ) : null}
      {SUB_TOPIC_BODY_FIELDS.map(([key, label]) => (
        <SubTopicLine key={key} label={label} text={subTopic[key]} />
      ))}
      {subTopic.questions.length ? (
        <ul className={REPORT_LIST_CLASSES}>
          {subTopic.questions.map((question, i) => (
            <li key={`${question}-${i}`}>{question}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// "Research directions" section of the research-overview report; renders
// nothing until the report has research directions.
export function ResearchDirectionsSection({
  overview,
}: {
  overview: ResearchOverview | undefined;
}) {
  const directions = directionEntries(overview);
  if (!directions.length) return null;
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Research directions</h3>
      <DirectionsPreview directions={directions} />
      {directions.map((direction, index) => (
        <div key={direction.title || index}>
          <h4 className={REPORT_H4_CLASSES}>{direction.title}</h4>
          {direction.importance ? <p>{direction.importance}</p> : null}
          {direction.recentFindings ? (
            <p>
              <strong>Recent findings: </strong>
              {direction.recentFindings}
            </p>
          ) : null}
          {direction.experiments.length ? (
            <ul className={REPORT_LIST_CLASSES}>
              {direction.experiments.map((experiment, i) => (
                <li key={`${experiment}-${i}`}>{experiment}</li>
              ))}
            </ul>
          ) : null}
          {direction.subTopics.map((subTopic, i) => (
            <SubTopicItem key={subTopic.title || i} subTopic={subTopic} />
          ))}
        </div>
      ))}
    </section>
  );
}

// Run-wide Agent Insights in the research overview.

// Quiet one-liner for a report section the engine could not generate after
// repeated attempts (its LLM output degraded to a placeholder fallback, L7).
// Exported so the overview tab's other degraded sections render the same
// notice; token classes only, matching the document's muted copy.
export const DEGRADED_SECTION_NOTICE_CLASSES =
  'text-[0.86rem] italic text-cosci-muted';

export const DEGRADED_SECTION_NOTICE_TEXT =
  'This section could not be generated after repeated attempts.';

// Engine node/schema names whose output feeds the overview tab's sections,
// used to match the report's degraded_sections list (L7).
export const META_REVIEW_SCHEMA = 'meta_review';
export const RESEARCH_OVERVIEW_SCHEMA = 'research_overview';

/** The shared L7 notice: a section the engine could not generate. */
export function DegradedSectionNotice() {
  return (
    <p className={DEGRADED_SECTION_NOTICE_CLASSES}>
      {DEGRADED_SECTION_NOTICE_TEXT}
    </p>
  );
}

// What each lost capability is called where a reader can recognize it.
// Anything the engine names that this map does not know is dropped rather
// than printed raw: an unexplained engine identifier in a report reads as
// a bug, and the sentence is still true without it.
const LOST_CAPABILITY_LABELS: Record<string, string> = {
  literature_review: 'the literature review',
  observation_review: 'observation reviews',
  deep_research: 'follow-up research',
  review_evidence: 'evidence for the deep reviews',
  verification_probes: 'verification probes',
  evolution_grounding: 'grounding for evolved ideas',
};

// The strongest source left, worst first.
const FLOOR_LABELS: Record<string, string> = {
  none: 'Nothing else was available to search.',
  run_attachments:
    'Only the documents attached to this run were available to search.',
};

/**
 * A run-level notice: this run could reach no literature source.
 *
 * Worth its own notice rather than a per-section one. A run that cannot
 * retrieve still completes and still writes an ordinary-looking report --
 * the ideas in it were simply never checked against a paper, and no part
 * of the output says so.
 *
 * @param report The run's persisted report, when one exists yet.
 * @returns The notice, or null on a run that retrieved normally.
 */
export function RetrievalDegradationNotice({report}: {report: Report | null}) {
  const degradation = report?.payload.retrieval_degradation;
  if (!degradation) return null;
  return (
    <p className={DEGRADED_SECTION_NOTICE_CLASSES}>
      {retrievalDegradationText(degradation)}
    </p>
  );
}

// The notice's sentence, built apart from the component so neither the
// label lookups nor the empty cases live inside the render.
function retrievalDegradationText(degradation: {
  lost: string[];
  floor: string;
}): string {
  const lost = (degradation.lost ?? [])
    .map(name => LOST_CAPABILITY_LABELS[name])
    .filter(label => !!label);
  const without = lost.length
    ? `, so it ran without ${joinReadable(lost)}`
    : '';
  const floor = FLOOR_LABELS[degradation.floor] ?? '';
  return `No literature source was reachable during this run${without}. ${floor}`.trim();
}

// "a, b and c" -- the report is prose, and a bare comma list reads as a
// dump of field names.
function joinReadable(items: string[]): string {
  if (items.length < 2) return items[0] ?? '';
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/**
 * Whether the run's report names `schema` among its degraded sections.
 *
 * @param report The run's persisted report, when one exists yet.
 * @param schema The engine node/schema name a section renders from.
 * @returns True when that section degraded to a fallback for this run.
 */
export function sectionDegraded(
  report: Report | null,
  schema: string,
): boolean {
  return (report?.payload.degraded_sections ?? []).includes(schema);
}

// An empty insights payload, so a degraded run with no insights object still
// renders the section (heading + notice) without optional chaining below.
const EMPTY_INSIGHTS: Required<AgentInsights> = {
  key_findings: [],
  uncertainties: [],
  contradictions: [],
  recommended_directions: [],
  next_experiments: [],
};

// One plain insight list. Blank entries are dropped so a list of empty strings
// cannot render a heading with nothing beneath it.
function InsightList({title, values}: {title: string; values: string[]}) {
  const items = (values ?? [])
    .map(value => readableText(value).trim())
    .filter(value => value.length > 0);
  if (!items.length) return null;
  return (
    <div>
      <h4 className={REPORT_H4_CLASSES}>{title}</h4>
      <ul className={REPORT_LIST_CLASSES}>
        {items.map(item => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

// Split one recommendation into its display fields. A persisted report from
// before recommendations kept their structure holds a single flattened string,
// which stays readable as the recommendation itself.
function toRecommendation(raw: RecommendedDirection | string) {
  if (typeof raw === 'string') {
    return {
      focusArea: '',
      recommendation: readableText(raw).trim(),
      justification: '',
    };
  }
  return {
    focusArea: readableText(raw?.focus_area).trim(),
    recommendation: readableText(raw?.recommendation).trim(),
    justification: readableText(raw?.justification).trim(),
  };
}

// Strategic recommendations keep their three fields apart: the focus area
// labels the entry, the recommendation is the advice, and the justification is
// the reasoning behind it -- flattening them into one line reads as raw data.
function RecommendedDirections({
  directions,
}: {
  directions: (RecommendedDirection | string)[];
}) {
  const entries = (directions ?? [])
    .map(toRecommendation)
    .filter(entry => entry.recommendation || entry.focusArea);
  if (!entries.length) return null;
  return (
    <div>
      <h4 className={REPORT_H4_CLASSES}>Recommended directions</h4>
      {entries.map(entry => (
        <div key={entry.focusArea + entry.recommendation} className="mt-3">
          {entry.focusArea ? (
            <p className="font-medium">{entry.focusArea}</p>
          ) : null}
          <p>{entry.recommendation}</p>
          {entry.justification ? (
            <p className="text-cosci-muted">{entry.justification}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

/**
 * The run-wide Agent Insights block: findings and uncertainty without leaking
 * private reasoning traces.
 *
 * `degraded` marks a run whose meta-review synthesis fell back to a
 * placeholder after repeated parse failures (L7): the meta-review-derived
 * lists (uncertainties, recommended directions) are then blank, so the
 * section says it degraded instead of presenting silence as normal.
 */
export function AgentInsightsSection({
  insights,
  degraded = false,
}: {
  insights: AgentInsights | undefined;
  degraded?: boolean;
}) {
  if (!insights && !degraded) return null;
  return (
    <AgentInsightsBody
      content={completeInsights(insights ?? EMPTY_INSIGHTS)}
      degraded={degraded}
    />
  );
}

// Saved reports can carry an empty insights object; normalize once.
function completeInsights(content: AgentInsights): Required<AgentInsights> {
  return {...EMPTY_INSIGHTS, ...content};
}

// The section body over a guaranteed-present insights payload.
function AgentInsightsBody({
  content,
  degraded,
}: {
  content: Required<AgentInsights>;
  degraded: boolean;
}) {
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Agent Insights</h3>
      {degraded ? <DegradedSectionNotice /> : null}
      <InsightList title="Key findings" values={content.key_findings} />
      <InsightList title="Uncertainties" values={content.uncertainties} />
      <InsightList title="Contradictions" values={content.contradictions} />
      <RecommendedDirections directions={content.recommended_directions} />
      <InsightList title="Next experiments" values={content.next_experiments} />
    </section>
  );
}

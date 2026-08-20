// The run-wide Agent Insights block of the overview tab, split out of
// run_detail_overview.tsx to keep that module under the file-length ceiling.
import {
  type AgentInsights,
  type RecommendedDirection,
  type Report,
} from '@/api/runs';
import {readableText} from '@/lib/text';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
} from './run_detail_document';

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

// The strongest source left, worst first. The corpus reads differently
// from the other two on purpose: it is the only floor a run can keep
// doing real research on, so it says the research continued rather than
// naming what was left lying around.
const FLOOR_LABELS: Record<string, string> = {
  none: 'Nothing else was available to search.',
  run_attachments:
    'Only the documents attached to this run were available to search.',
  group_corpus:
    "Research continued against the group's own papers, held locally.",
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
const EMPTY_INSIGHTS: AgentInsights = {
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
      content={insights ?? EMPTY_INSIGHTS}
      degraded={degraded}
    />
  );
}

// The section body over a guaranteed-present insights payload.
function AgentInsightsBody({
  content,
  degraded,
}: {
  content: AgentInsights;
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

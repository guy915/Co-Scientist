// The run-wide Agent Insights block of the overview tab, split out of
// run_detail_overview.tsx to keep that module under the file-length ceiling.
import {type AgentInsights, type RecommendedDirection} from '@/api/runs';
import {readableText} from '@/lib/text';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
} from './run_detail_document';

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
 */
export function AgentInsightsSection({
  insights,
}: {
  insights: AgentInsights | undefined;
}) {
  if (!insights) return null;
  const sections: [string, string[]][] = [
    ['Key findings', insights.key_findings],
    ['Uncertainties', insights.uncertainties],
    ['Contradictions', insights.contradictions],
  ];
  return (
    <section className={REPORT_SECTION_CLASSES}>
      <h3 className={REPORT_H3_CLASSES}>Agent Insights</h3>
      {sections.map(([title, values]) => (
        <InsightList key={title} title={title} values={values} />
      ))}
      <RecommendedDirections
        directions={insights.recommended_directions ?? []}
      />
      <InsightList
        title="Next experiments"
        values={insights.next_experiments}
      />
    </section>
  );
}

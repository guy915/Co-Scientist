// The "Research directions" section of the research-overview report, split
// out of run_detail_overview.tsx to keep both files under the line ceiling.
import {isRecord, readableText, readableTextList} from '@/lib/text';
import type {ResearchOverview} from '@/api/runs';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_LIST_CLASSES,
  REPORT_SECTION_CLASSES,
} from './run_detail_document';

interface SubTopicEntry {
  title: string;
  why: string;
  what: string;
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
    questions: readableTextList(record.specific_questions),
  };
}

// Normalize a direction's sub-topics into renderable entries, dropping any
// that carry no content after coercion.
function subTopicEntries(raw: unknown): SubTopicEntry[] {
  const list = Array.isArray(raw) ? raw : [];
  return list
    .map(toSubTopicEntry)
    .filter(e => e.title || e.why || e.what || e.questions.length);
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

// One named sub-topic entry, or nothing when coercion left it empty.
function SubTopicItem({subTopic}: {subTopic: SubTopicEntry}) {
  return (
    <div>
      {subTopic.title ? (
        <p>
          <strong>{subTopic.title}</strong>
        </p>
      ) : null}
      {subTopic.why ? (
        <p>
          <strong>Why: </strong>
          {subTopic.why}
        </p>
      ) : null}
      {subTopic.what ? (
        <p>
          <strong>What: </strong>
          {subTopic.what}
        </p>
      ) : null}
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

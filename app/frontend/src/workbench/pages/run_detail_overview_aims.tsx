// The "Specific aims" section of the research-overview report, split out of
// run_detail_overview.tsx to keep both files under the line ceiling.
import {isRecord, readableText} from '@/lib/text';
import type {ResearchOverview} from '@/api/runs';
import {
  REPORT_H3_CLASSES,
  REPORT_H4_CLASSES,
  REPORT_SECTION_CLASSES,
} from './run_detail_document';

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
        <SpecificAim key={index} aim={aim} />
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
// Per-aim fields, each labelled except the heading. Only one spelling of
// each is ever present, so the whole list renders in order.
const AIM_BODY_FIELDS = [
  ['hypothesis', 'Hypothesis'],
  ['reasoning', 'Reasoning'],
  ['rationale', ''],
  ['approach', ''],
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
function SpecificAim({aim}: {aim: unknown}) {
  const record = isRecord(aim) ? aim : {};
  const title =
    readableText(record.overarching_goal) || readableText(record.aim);
  return (
    <div>
      <h4 className={REPORT_H4_CLASSES}>{title}</h4>
      {AIM_BODY_FIELDS.map(([key, label]) => {
        const text = readableText(record[key]);
        if (!text) return null;
        return (
          <p key={key}>
            {label ? <strong>{label}: </strong> : null}
            {text}
          </p>
        );
      })}
    </div>
  );
}

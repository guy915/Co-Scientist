import {renderInlineHtml} from './sanitize_html';

/**
 * Structured-abstract handling for PubMed content.
 *
 * PubMed/NLM structured abstracts prepend a section label (BACKGROUND, METHODS,
 * RESULTS, ...) to each section's text and concatenate the sections into a
 * single string with no reliable separator: an all-caps label runs straight
 * into its body ("SUMMARYThe global..."), while a title-case label is followed
 * by two spaces ("Background  Major..."). Rendered verbatim, sections run
 * together and are hard to read. This module splits such a string back into
 * labeled sections so each can render as its own paragraph.
 */

/** Canonical NLM categories plus commonly-seen section labels (uppercase). */
const SECTION_LABELS = [
  'MATERIALS AND METHODS',
  'MAIN OUTCOME MEASURES',
  'MAIN OUTCOME MEASURE',
  'BACKGROUND',
  'OBJECTIVES',
  'OBJECTIVE',
  'CONCLUSIONS',
  'CONCLUSION',
  'INTRODUCTION',
  'INTERPRETATION',
  'INTERVENTIONS',
  'INTERVENTION',
  'MEASUREMENTS',
  'PARTICIPANTS',
  'LIMITATIONS',
  'IMPORTANCE',
  'DISCUSSION',
  'RATIONALE',
  'FINDINGS',
  'PURPOSE',
  'METHODS',
  'METHOD',
  'RESULTS',
  'SUMMARY',
  'SETTING',
  'CONTEXT',
  'FUNDING',
  'DESIGN',
  'AIMS',
  'AIM',
];

export interface AbstractSection {
  /** Display label (title-cased) or null for unlabeled text. */
  label: string | null;
  /** Sanitized inline HTML, safe for `dangerouslySetInnerHTML`. */
  html: string;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** "SUMMARY" -> "Summary", "MAIN OUTCOME MEASURES" -> "Main outcome measures". */
function titleCase(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1).toLowerCase();
}

const sortedLabels = [...SECTION_LABELS].sort((a, b) => b.length - a.length);
const upperForms = sortedLabels.map(escapeRegExp).join('|');
const titleForms = sortedLabels.map(l => escapeRegExp(titleCase(l))).join('|');

// A label counts as a section header when it sits at the start of the string or
// after sentence-ending punctuation/whitespace, and is followed by a colon, two
// or more spaces, or (all-caps labels only) a directly-adjacent capitalized
// word. The two-space requirement keeps ordinary prose ("Results were ...")
// from being mistaken for a header. Case-sensitive so the capital-letter
// lookahead stays meaningful.
const LABEL_RE = new RegExp(
  '(?:^|(?<=[.)\\s]))' +
    `(?:(${upperForms})(?::\\s*|\\s{2,}|(?=[A-Z][a-z]))` +
    `|(${titleForms})(?::\\s*|\\s{2,}))`,
  'g',
);

/**
 * Splits a possibly-structured abstract into labeled sections with sanitized
 * bodies. An unstructured abstract returns a single section with a null label.
 *
 * @param raw The untrusted abstract text (may contain inline HTML).
 * @returns One section per detected label, in document order.
 */
export function splitAbstractSections(raw: string): AbstractSection[] {
  const text = raw ?? '';
  const marks: Array<{start: number; end: number; label: string}> = [];
  LABEL_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = LABEL_RE.exec(text)) !== null) {
    marks.push({
      start: match.index,
      end: LABEL_RE.lastIndex,
      label: match[1] ?? match[2],
    });
    if (LABEL_RE.lastIndex === match.index) LABEL_RE.lastIndex++;
  }

  const sections: AbstractSection[] = [];
  const pushSection = (label: string | null, body: string) => {
    const trimmed = body.trim();
    if (trimmed) sections.push({label, html: renderInlineHtml(trimmed)});
  };

  if (marks.length === 0) {
    pushSection(null, text);
    return sections.length ? sections : [{label: null, html: ''}];
  }

  // Any text before the first label is unlabeled lead-in.
  pushSection(null, text.slice(0, marks[0].start));
  marks.forEach((mark, index) => {
    const bodyEnd =
      index + 1 < marks.length ? marks[index + 1].start : text.length;
    pushSection(titleCase(mark.label), text.slice(mark.end, bodyEnd));
  });

  return sections.length
    ? sections
    : [{label: null, html: renderInlineHtml(text.trim())}];
}

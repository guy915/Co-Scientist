import {renderInlineHtml} from './sanitize_html';

/**
 * Shorten a research goal into a concise, single-line session title for run
 * lists and the history sidebar, mirroring Google's compact "Chats" list,
 * which shows short titles rather than the full prompt.
 *
 * Heuristic (no LLM): take the first clause, cap to a readable length on a word
 * boundary, drop a dangling short word, and add an ellipsis when truncated.
 *
 * @param goal The full research goal / prompt.
 * @param maxChars Maximum length before truncation.
 * @returns A concise title (never empty).
 */
export function conciseTitle(goal: string, maxChars = 52): string {
  const trimmed = (goal ?? '').trim();
  if (!trimmed) return 'Untitled session';
  const firstClause = firstSentenceClause(trimmed);
  if (firstClause.length <= maxChars) return firstClause;
  return truncateOnWordBoundary(firstClause, maxChars);
}

/**
 * The first sentence/clause of a research goal, split on sentence-ending
 * punctuation followed by whitespace/end — so an abbreviation like
 * "M.tuberculosis" (period mid-word) is not mistaken for a clause boundary and
 * truncated to "...for M". Returns '' for empty input.
 *
 * Exported for width-aware titles (e.g. the recents cards) that render this
 * clause through TruncatedLabel instead of the char-capped conciseTitle: the
 * label fills the available width and ellipsizes on a word boundary, matching
 * every other truncation in the UI.
 */
export function firstSentenceClause(text: string): string {
  const source = (text ?? '').trim();
  const sentenceEnd = source.search(/[.?!;](\s|$)/);
  return (sentenceEnd >= 0 ? source.slice(0, sentenceEnd) : source).trim();
}

/**
 * Capitalizes a listed term's first letter, where doing so is safe.
 *
 * The four setup fields are written by the model, which capitalizes its
 * preference sentences and leaves focus-area noun phrases lowercase, so the
 * two lists in the same specification card disagreed about their own house
 * style ("Prioritize mechanistic novelty" above "gut-brain axis").
 *
 * Only a first *word* that is entirely lowercase ASCII is touched. Scientific
 * terms make the naive version wrong in two directions a reader would notice:
 * "α-synuclein aggregation" must not become "Α-synuclein" (that is a Greek
 * capital alpha, and journals set the prefix lowercase), and "mRNA stability"
 * must not become "MRNA stability". Both are left exactly as the model wrote
 * them, which is also how they should be set.
 */
export function capitalizeTerm(term: string): string {
  const text = term.trim();
  const firstWord = text.split(/\s/, 1)[0] ?? '';
  if (!/^[a-z][a-z-]*$/.test(firstWord)) return text;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Coerce a possibly-malformed structured-output field into readable text.
 *
 * Research-overview fields are produced by the model in json_object mode with
 * no server-side schema enforcement, so a field the schema declares a string
 * can arrive as an object, or as a string that is itself serialized JSON.
 * Rendering that verbatim leaks raw JSON into the UI. This flattens any of
 * those shapes into human-readable text: a JSON-looking string is parsed and
 * flattened, an object is rendered as its values joined by an em dash, and a
 * well-formed string passes through unchanged.
 */
export function readableText(value: unknown): string {
  if (typeof value === 'string') return readableFromString(value);
  if (Array.isArray(value)) return joinReadable(value, ' ');
  if (isRecord(value)) return joinReadable(Object.values(value), ' - ');
  return primitiveText(value);
}

/**
 * Coerce a possibly-malformed list field (e.g. `suggested_experiments`) into
 * an array of readable strings, tolerating a JSON-encoded string, a lone
 * object, or a list whose items are objects or serialized JSON.
 */
export function readableTextList(value: unknown): string[] {
  if (typeof value === 'string') return listFromString(value);
  if (Array.isArray(value)) return mapReadable(value);
  if (isRecord(value)) return mapReadable([value]);
  return [];
}

function readableFromString(value: string): string {
  const trimmed = value.trim();
  if (!isJsonLike(trimmed)) return value;
  try {
    return readableText(JSON.parse(trimmed));
  } catch {
    return value;
  }
}

function listFromString(value: string): string[] {
  const trimmed = value.trim();
  if (!trimmed) return [];
  if (!isJsonLike(trimmed)) return [trimmed];
  try {
    return readableTextList(JSON.parse(trimmed));
  } catch {
    return [trimmed];
  }
}

function isJsonLike(text: string): boolean {
  return (
    (text.startsWith('{') && text.endsWith('}')) ||
    (text.startsWith('[') && text.endsWith(']'))
  );
}

/** Whether a value can be indexed as a record (arrays included). */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function joinReadable(values: unknown[], separator: string): string {
  return values.map(readableText).filter(Boolean).join(separator);
}

function mapReadable(values: unknown[]): string[] {
  return values.map(readableText).filter(Boolean);
}

function primitiveText(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value);
}

/**
 * Truncates `text` on a word boundary and always ends in a bare ellipsis
 * ("word…"): drops the partial trailing word and any dangling very short
 * word, and never leaves a trailing space or separator before the ellipsis.
 */
function truncateOnWordBoundary(text: string, maxChars: number): string {
  const cut = text.slice(0, maxChars);
  const lastSpace = cut.lastIndexOf(' ');
  const onBoundary = lastSpace > 0 ? cut.slice(0, lastSpace) : cut;
  const base = onBoundary.replace(/[\s,;:]+$/, '');
  const trimmedTail = (base.replace(/\s+\S{1,3}$/, '') || base).replace(
    /[\s,;:]+$/,
    '',
  );
  return `${trimmedTail}…`;
}

const HOUR_SECONDS = 3600; // threshold above which durations render in hours
const MINUTE_SECONDS = 60;

/** Renders `value` with its unit, pluralized. */
function pluralize(value: number, unit: string): string {
  return `${value} ${unit}${value === 1 ? '' : 's'}`;
}

/**
 * Formats a duration in seconds as a rounded human phrase, e.g. "3 hours" or
 * "12 minutes". Durations of at least one hour render in hours; shorter ones
 * render in minutes (never below "1 minute").
 *
 * @param seconds Elapsed time in seconds.
 * @param options.subMinute When true, spans below one minute render as
 *   "< 1 minute" instead of rounding up to "1 minute".
 * @returns A pluralized duration phrase.
 */
export function formatDurationPhrase(
  seconds: number,
  options?: {subMinute?: boolean},
): string {
  if (seconds >= HOUR_SECONDS) {
    return pluralize(Math.round(seconds / HOUR_SECONDS), 'hour');
  }
  if (options?.subMinute && seconds < MINUTE_SECONDS) return '< 1 minute';
  const minutes = Math.max(1, Math.round(seconds / MINUTE_SECONDS));
  return pluralize(minutes, 'minute');
}

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

/** One labeled (or unlabeled) segment of a structured abstract. */
export interface AbstractSection {
  /** Display label (title-cased) or null for unlabeled text. */
  label: string | null;
  /** Sanitized inline HTML, safe for `dangerouslySetInnerHTML`. */
  html: string;
}

/**
 * Escapes regex metacharacters so `value` can be embedded literally in a
 * pattern.
 */
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * "SUMMARY" -> "Summary", "MAIN OUTCOME MEASURES" -> "Main outcome
 * measures".
 */
function titleCase(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1).toLowerCase();
}

// Sorted longest-first so a multi-word label like "MATERIALS AND METHODS"
// wins the alternation before the shorter "METHODS" form can match a prefix.
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
 * Finds every section-label occurrence in `text`, in document order.
 *
 * @param text The abstract text to scan for labels.
 * @returns One mark per detected label, with its match bounds.
 */
function findLabelMarks(
  text: string,
): {start: number; end: number; label: string}[] {
  const marks: {start: number; end: number; label: string}[] = [];
  LABEL_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = LABEL_RE.exec(text)) !== null) {
    marks.push({
      start: match.index,
      end: LABEL_RE.lastIndex,
      label: match[1] ?? match[2],
    });
    // Guards against an infinite loop on a zero-length match (lastIndex would
    // otherwise never advance).
    if (LABEL_RE.lastIndex === match.index) LABEL_RE.lastIndex++;
  }
  return marks;
}

// Returns `sections`, or (when every detected piece trimmed to nothing) a
// single unlabeled fallback section built from the original `text`.
function withFallback(
  sections: AbstractSection[],
  text: string,
): AbstractSection[] {
  if (sections.length) return sections;
  const trimmed = text.trim();
  return [{label: null, html: trimmed ? renderInlineHtml(trimmed) : ''}];
}

/**
 * Splits a possibly-structured abstract into labeled sections with sanitized
 * bodies. An unstructured abstract returns a single section with a null label.
 *
 * @param raw The untrusted abstract text (may contain inline HTML).
 * @returns One section per detected label, in document order.
 */
export function splitAbstractSections(raw: string): AbstractSection[] {
  const text = raw ?? '';
  const marks = findLabelMarks(text);

  const sections: AbstractSection[] = [];
  // Skips empty sections, e.g. a detected label with no body text before the
  // next one (or before the end of the string).
  const pushSection = (label: string | null, body: string) => {
    const trimmed = body.trim();
    if (trimmed) sections.push({label, html: renderInlineHtml(trimmed)});
  };

  // Any text before the first label is unlabeled lead-in; with no labels at
  // all, that lead-in is the whole abstract (a single unlabeled section).
  pushSection(null, text.slice(0, marks[0]?.start ?? text.length));
  marks.forEach((mark, index) => {
    const bodyEnd =
      index + 1 < marks.length ? marks[index + 1].start : text.length;
    pushSection(titleCase(mark.label), text.slice(mark.end, bodyEnd));
  });

  return withFallback(sections, text);
}

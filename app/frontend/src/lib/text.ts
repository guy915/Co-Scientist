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

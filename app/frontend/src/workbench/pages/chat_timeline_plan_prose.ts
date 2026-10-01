/**
 * @fileoverview Reduces the interview's completing turn to the prose that is
 * not the plan.
 *
 * The plan document rendered below this turn is the single home for the
 * plan: editable, authoritative, and the copy the run is actually created
 * from. Prose that restates the same five fields is the model saying
 * everything twice on one screen.
 *
 * The prompt is where that is settled -- the "# Completion" section of
 * `app/app/interviews/prompts.py` used to ask the completing turn to
 * "present the finalized scope as a structured summary" with a heading per
 * part, and now tells it not to restate the fields at all. This module is
 * the belt to that braces: a model asked not to do something still
 * sometimes does, and the cost of the summary slipping through is the
 * defect the reader already reported once.
 *
 * It takes only the restated copy out and leaves everything the model wrote
 * around it: its own lead-in, any heading of its own, and the sign-off that
 * closes the turn.
 *
 * A section is recognised by its heading naming one of the five fields, so
 * a turn written in another language keeps its summary -- the duplication
 * stays visible there rather than the wrong paragraphs being cut. The
 * prompt covers that case; this cannot.
 */

// The headings the summary opens each part with, as the five fields are
// named to the model (`interviews/prompts.py`, "# The five fields") and as
// the plan document labels them. Near-misses are listed because the model
// paraphrases: it is asked for a heading per part, never for these exact
// words.
const PLAN_FIELD_HEADINGS = new Set([
  'research challenge',
  'research goal',
  'research question',
  'challenge',
  'goal',
  'focus area',
  'focus areas',
  'focus',
  'preference',
  'preferences',
  'lab constraint',
  'lab constraints',
  'laboratory constraints',
  'constraints',
  'title',
]);

const HEADING_PATTERN = /^ {0,3}#{1,6} +(.*?) *#* *$/;

// A line that is part of a list, table, quote or heading rather than of a
// plain paragraph.
const STRUCTURED_LINE = /^ {0,3}([#>|]|[-*+] |\d+[.)] )/;

// A horizontal rule, which the model uses to separate the summary's parts.
const RULE_LINE = /^ {0,3}(-{3,}|\*{3,}|_{3,}) *$/;

// A heading's text, stripped to what it names: emphasis markers, numbering,
// a trailing parenthetical and trailing punctuation all vary between turns
// and none of them change which field the heading is about. The
// parenthetical is not hypothetical -- a live turn headed its title section
// "Title (proposed)", which is the section anyway.
function headingLabel(line: string): string | null {
  const match = HEADING_PATTERN.exec(line);
  if (!match) return null;
  return match[1]
    .replace(/[*_`\\]/g, '')
    .replace(/^\d+[.)]\s*/, '')
    .replace(/\s*\([^)]*\)\s*$/, '')
    .replace(/[:.\-–—]+\s*$/, '')
    .trim()
    .toLowerCase();
}

// Every line except those under a heading that names a plan field. A field
// heading opens a dropped run; the next heading of any kind closes it.
function withoutFieldSections(source: string): string {
  const kept: string[] = [];
  let dropping = false;
  for (const line of source.split('\n')) {
    const label = headingLabel(line);
    if (label !== null) dropping = PLAN_FIELD_HEADINGS.has(label);
    if (!dropping) kept.push(line);
  }
  return kept.join('\n');
}

function isBlankOrRule(line: string): boolean {
  return !line.trim() || RULE_LINE.test(line);
}

// Drops the blank lines and separator rules left dangling where a section
// was cut out, and collapses the gaps between what survived.
function tidy(text: string): string {
  const lines = text.split('\n');
  while (lines.length && isBlankOrRule(lines[0])) lines.shift();
  while (lines.length && isBlankOrRule(lines[lines.length - 1])) lines.pop();
  return lines.join('\n').replace(/\n{3,}/g, '\n\n');
}

/**
 * The turn's closing sentence, when it ends on one.
 *
 * The completing turn is asked to end by saying the run can be started or
 * the scope refined further, and it writes that after the summary -- which
 * puts it inside the last section cut above even though it is not part of
 * the plan. Recognised by position and shape: the last paragraph of the
 * turn, made only of prose lines.
 */
function signOff(source: string): string {
  const blocks = source.split(/\n[ \t]*\n/);
  const last = (blocks[blocks.length - 1] ?? '').trim();
  if (!last) return '';
  const structured = last.split('\n').some(line => STRUCTURED_LINE.test(line));
  return structured ? '' : last;
}

/**
 * The completing interview turn as the plan turn shows it: everything the
 * model wrote except its restatement of the plan.
 *
 * @param intro The Agent's closing message, as persisted.
 * @returns The prose to render above the plan document; empty when the turn
 *   was nothing but the summary and carried no sign-off, which leaves the
 *   card on its own generic lead-in.
 */
export function planLeadIn(intro?: string): string {
  const source = (intro ?? '').trim();
  if (!source) return '';
  return withSignOff(tidy(withoutFieldSections(source)), signOff(source));
}

// Puts the sign-off back under whatever survived, unless it is already
// there (a turn that carried no summary keeps its own last paragraph).
function withSignOff(kept: string, closing: string): string {
  if (!closing || kept.endsWith(closing)) return kept;
  return kept ? `${kept}\n\n${closing}` : closing;
}

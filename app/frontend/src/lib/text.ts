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

// First sentence only, but split on sentence-ending punctuation followed by
// whitespace/end — so an abbreviation like "M.tuberculosis" (period mid-word)
// is not mistaken for a clause boundary and truncated to "...for M".
function firstSentenceClause(text: string): string {
  const sentenceEnd = text.search(/[.?!;](\s|$)/);
  return (sentenceEnd >= 0 ? text.slice(0, sentenceEnd) : text).trim();
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

/**
 * Shorten a research goal into a concise, single-line session title for run
 * lists and the history sidebar — mirroring Gemini Enterprise's "Chats" list,
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
  const firstClause = (trimmed.split(/[.?!;]/)[0] || trimmed).trim();
  if (firstClause.length <= maxChars) return firstClause;
  const cut = firstClause.slice(0, maxChars);
  const lastSpace = cut.lastIndexOf(' ');
  const onBoundary = lastSpace > 20 ? cut.slice(0, lastSpace) : cut;
  const base = onBoundary.replace(/[\s,;:]+$/, '');
  const trimmedTail = base.replace(/\s+\S{1,3}$/, '');
  return `${trimmedTail || base}…`;
}

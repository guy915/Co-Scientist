/**
 * Returns true if a hypothesis matches the pinned text, either by direct text
 * match or through its evolution_history (which records ancestor hypothesis texts).
 */
export function isTrackedHypothesis(
  hyp: { text?: string; hypothesis?: string; evolution_history?: string[] },
  pinnedText: string
): boolean {
  const text = hyp.text || hyp.hypothesis || "";
  if (text === pinnedText) return true;
  if (hyp.evolution_history?.includes(pinnedText)) return true;
  return false;
}

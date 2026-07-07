/**
 * Canonical keyword test for the liver-fibrosis / MASLD / MASH demo domain.
 *
 * This predicate previously lived, subtly divergent, in five call sites: the
 * run-spec inference, the chat setup card, the run-detail title override, and
 * two demo-record generators. The keyword set is the union of all five (bare
 * "fibrosis", MASLD, MASH, and "hepatic stellate"), matched on word boundaries
 * so tokens like MASH are not found inside unrelated words (e.g. "smashed").
 *
 * @param goal Research goal text to classify.
 * @returns True when the goal reads as a liver-fibrosis demo goal.
 */
export function isLiverFibrosisGoal(goal: string): boolean {
  return /\b(?:fibrosis|masld|mash|hepatic stellate)\b/i.test(goal);
}

/**
 * De-duplicates items by id and orders them newest-first.
 *
 * Later items with a duplicate id win (so a second source overrides the first),
 * then the result is sorted by descending update time. Shared by the run
 * history loader and the offline record store so both use one merge policy.
 *
 * @param items Items to merge, in priority order (later entries win ties).
 * @param getId Extracts the de-duplication key from an item.
 * @param getUpdatedAt Extracts the sort key (higher = newer) from an item.
 * @returns The de-duplicated items, newest first.
 */
export function mergeByIdNewestFirst<T>(
  items: readonly T[],
  getId: (item: T) => string,
  getUpdatedAt: (item: T) => number,
): T[] {
  const byId = new Map<string, T>();
  for (const item of items) byId.set(getId(item), item);
  return [...byId.values()].sort((a, b) => getUpdatedAt(b) - getUpdatedAt(a));
}

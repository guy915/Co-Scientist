/**
 * Joins className fragments into one class string, dropping falsy entries so
 * call sites can express conditional classes inline:
 *
 *     joinClasses(BASE_CLASSES, active && ACTIVE_CLASSES)
 */
export function joinClasses(
  ...classes: (string | false | null | undefined)[]
): string {
  return classes.filter(Boolean).join(' ');
}

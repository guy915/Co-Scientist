const HOUR_SECONDS = 3600; // threshold above which durations render in hours
const MINUTE_SECONDS = 60;

/** Renders `value` with its unit, pluralized. */
function pluralize(value: number, unit: string): string {
  return `${value} ${unit}${value === 1 ? '' : 's'}`;
}

/** Whether a duration should render as the "< 1 minute" placeholder. */
function isSubMinute(
  seconds: number,
  options?: {subMinute?: boolean},
): boolean {
  return Boolean(options?.subMinute) && seconds < MINUTE_SECONDS;
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
  if (isSubMinute(seconds, options)) return '< 1 minute';
  const minutes = Math.max(1, Math.round(seconds / MINUTE_SECONDS));
  return pluralize(minutes, 'minute');
}

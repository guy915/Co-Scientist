const HOUR_SECONDS = 3600; // threshold above which durations render in hours
const MINUTE_SECONDS = 60;

/**
 * Formats a duration in seconds as a rounded human phrase, e.g. "3 hours" or
 * "12 minutes". Durations of at least one hour render in hours; shorter ones
 * render in minutes (never below "1 minute").
 *
 * @param seconds Elapsed time in seconds.
 * @returns A pluralized duration phrase.
 */
export function formatDurationPhrase(seconds: number): string {
  if (seconds >= HOUR_SECONDS) {
    const hours = Math.round(seconds / HOUR_SECONDS);
    return `${hours} hour${hours === 1 ? '' : 's'}`;
  }
  const minutes = Math.max(1, Math.round(seconds / MINUTE_SECONDS));
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}

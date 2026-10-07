export function nowSeconds(): number {
  return Date.now() / 1000;
}

const HOUR_SECONDS = 3600;
const MINUTE_SECONDS = 60;

function pluralize(value: number, unit: string): string {
  return `${value} ${unit}${value === 1 ? '' : 's'}`;
}

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

// Activity rows: short relative stamps, in hours once past an hour so they
// agree with the duration phrases on the same page.
export function relativeTime(
  createdAt: number | undefined,
  now: number,
): string {
  if (!createdAt) return '';
  const seconds = Math.max(0, Math.round(now - createdAt));
  if (seconds < 5) return 'just now';
  if (seconds < MINUTE_SECONDS) return `${seconds}s ago`;
  if (seconds < HOUR_SECONDS)
    return `${Math.round(seconds / MINUTE_SECONDS)}m ago`;
  return `${Math.round(seconds / HOUR_SECONDS)}h ago`;
}

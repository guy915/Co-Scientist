import type {StreamEvent} from '@/hooks/use_run_stream';

/** One row of the live standings carried on every pipeline event. */
export interface LiveStanding {
  rank: number;
  id: string;
  title: string;
  elo: number;
  wins: number;
  losses: number;
}

function isStanding(value: unknown): value is LiveStanding {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.title === 'string' &&
    typeof v.elo === 'number' &&
    typeof v.rank === 'number'
  );
}

/**
 * Pick the most recent non-empty leaderboard snapshot from the event stream.
 *
 * Every engine and mock node event carries the current standings, so the
 * latest one reflects live progress before the run's final report exists
 * (the store is only populated when the run completes). Returns an empty
 * array when no event has emitted standings yet.
 *
 * @param events The streamed pipeline events, in arrival order.
 * @returns The latest standings, or an empty array.
 */
export function selectLiveLeaderboard(events: StreamEvent[]): LiveStanding[] {
  for (let i = events.length - 1; i >= 0; i--) {
    const raw = (events[i]?.payload as {leaderboard?: unknown} | undefined)
      ?.leaderboard;
    if (Array.isArray(raw) && raw.length > 0 && raw.every(isStanding)) {
      return raw;
    }
  }
  return [];
}

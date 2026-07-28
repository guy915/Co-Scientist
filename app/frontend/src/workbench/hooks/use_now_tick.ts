import {useEffect, useState} from 'react';

/**
 * Re-renders the caller on an interval so time-based UI (relative timestamps,
 * an elapsed clock) advances even when no new props, events, or fetches
 * arrive. Shared by the live-run view and the home recents cards, which both
 * show times that must keep moving while a run sits inside a slow node.
 *
 * @param intervalMs How often to re-read the clock, in milliseconds.
 * @returns The current time in Unix seconds, refreshed on each tick.
 */
export function useNowTick(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

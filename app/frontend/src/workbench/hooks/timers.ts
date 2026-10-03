import {useEffect, useState, useCallback, useRef} from 'react';

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

/**
 * A single-slot timeout whose pending callback is dropped on unmount.
 *
 * For the transient labels the shell's controls hold on themselves — Copy's
 * "Copied", Report's "Sent"/"Couldn't send" — where the state is set on an
 * action and expires on its own. Scheduling replaces any pending expiry
 * rather than stacking one behind it, so a rapid second action restarts its
 * own window instead of being cleared by the first one's leftover timer.
 *
 * @returns `schedule` (run `run` after `delayMs`, replacing any pending call)
 *   and `cancel` (drop a pending call). Both are stable across renders.
 */
export function useResetTimer(): {
  schedule: (run: () => void, delayMs: number) => void;
  cancel: () => void;
} {
  const timerRef = useRef<number | null>(null);

  const cancel = useCallback(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const schedule = useCallback(
    (run: () => void, delayMs: number) => {
      cancel();
      timerRef.current = window.setTimeout(run, delayMs);
    },
    [cancel],
  );

  // Never fire against an unmounted component.
  useEffect(() => cancel, [cancel]);

  return {schedule, cancel};
}

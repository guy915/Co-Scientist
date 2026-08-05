import {useCallback, useEffect, useRef} from 'react';

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

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

/** An optional action rendered as a button inside the toast. */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

/** A toast: a message and an optional action button. */
export interface ToastState {
  message: string;
  action?: ToastAction;
}

/** Shows or clears a toast; accepts the plain-string shorthand or null. */
export type ToastSetter = (value: string | ToastState | null) => void;

/**
 * Manages a transient toast that auto-clears after a delay. Accepts either a
 * plain string (message only) or a {@link ToastState} with an action button.
 *
 * @param durationMs How long the toast stays visible before clearing.
 * @returns The current toast (or null) and a setter to show or clear it.
 */
export function useToast(durationMs = 3000): {
  toast: ToastState | null;
  setToast: ToastSetter;
} {
  // Single-slot "queue": showing a new toast replaces the current one.
  const [toast, setToastState] = useState<ToastState | null>(null);

  // Stable setter that normalizes the string shorthand into ToastState, so
  // callers can pass it into deps arrays or child props freely.
  const setToast = useCallback((value: string | ToastState | null) => {
    setToastState(
      value === null
        ? null
        : typeof value === 'string'
          ? {message: value}
          : value,
    );
  }, []);

  // Auto-dismiss timer. `toast` in the deps restarts the countdown whenever
  // a new toast (a new object identity) is shown, and the cleanup cancels
  // the previous timer so a replaced toast gets the full duration -- it also
  // clears the pending timeout on unmount.
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToastState(null), durationMs);
    return () => window.clearTimeout(timer);
  }, [toast, durationMs]);

  return {toast, setToast};
}

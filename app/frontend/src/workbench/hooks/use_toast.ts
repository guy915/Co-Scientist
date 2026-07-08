import {useCallback, useEffect, useState} from 'react';

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

/**
 * Manages a transient toast that auto-clears after a delay. Accepts either a
 * plain string (message only) or a {@link ToastState} with an action button.
 *
 * @param durationMs How long the toast stays visible before clearing.
 * @returns The current toast (or null) and a setter to show or clear it.
 */
export function useToast(durationMs = 3000): {
  toast: ToastState | null;
  setToast: (value: string | ToastState | null) => void;
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

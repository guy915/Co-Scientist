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
  const [toast, setToastState] = useState<ToastState | null>(null);

  const setToast = useCallback((value: string | ToastState | null) => {
    setToastState(
      value === null
        ? null
        : typeof value === 'string'
          ? {message: value}
          : value,
    );
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToastState(null), durationMs);
    return () => window.clearTimeout(timer);
  }, [toast, durationMs]);

  return {toast, setToast};
}

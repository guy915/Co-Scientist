import {useEffect, useState, useCallback, useRef} from 'react';
import {nowSeconds} from '@/shared/lib/time';

export function useNowTick(intervalMs: number): number {
  const [now, setNow] = useState(nowSeconds);
  useEffect(() => {
    const id = window.setInterval(() => setNow(nowSeconds()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

// Replace pending expiry so repeated actions receive a full window; drop
// callbacks on unmount.
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

  useEffect(() => cancel, [cancel]);

  return {schedule, cancel};
}

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastState {
  message: string;
  action?: ToastAction;
}

export type ToastSetter = (value: string | ToastState | null) => void;

export function useToast(durationMs = 3000): {
  toast: ToastState | null;
  setToast: ToastSetter;
} {
  const [toast, setToastState] = useState<ToastState | null>(null);

  // Keep setter identity stable because consumers use it in dependencies and
  // child props.
  const setToast = useCallback((value: string | ToastState | null) => {
    setToastState(
      value === null
        ? null
        : typeof value === 'string'
          ? {message: value}
          : value,
    );
  }, []);

  // Replacement toast identity restarts its full expiry; cleanup prevents old
  // timers clearing later toasts or firing after unmount.
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToastState(null), durationMs);
    return () => window.clearTimeout(timer);
  }, [toast, durationMs]);

  return {toast, setToast};
}

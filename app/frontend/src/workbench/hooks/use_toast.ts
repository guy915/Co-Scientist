import {useEffect, useState} from 'react';

/**
 * Manages a transient toast string that auto-clears after a delay.
 *
 * @param durationMs How long the toast stays visible before clearing.
 * @returns The current toast (or null) and a setter to show or clear it.
 */
export function useToast(durationMs = 3000): {
  toast: string | null;
  setToast: (value: string | null) => void;
} {
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), durationMs);
    return () => window.clearTimeout(timer);
  }, [toast, durationMs]);

  return {toast, setToast};
}

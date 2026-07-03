import {useEffect, useMemo, useRef} from 'react';

/** A trailing-edge debounced function returned by {@link useDebouncedCallback}. */
export interface DebouncedCallback<T extends (...args: never[]) => void> {
  /** Schedules an invocation with these arguments after the delay elapses. */
  (...args: Parameters<T>): void;
  /** Runs a pending invocation immediately; no-op when nothing is pending. */
  flush: () => void;
  /** Drops a pending invocation without running it. */
  cancel: () => void;
}

/**
 * Returns a stable, trailing-edge debounced wrapper around a callback.
 *
 * Calls made within `delayMs` of each other collapse into a single invocation
 * that fires `delayMs` after the most recent call, using the most recent
 * arguments. The wrapper identity never changes across renders (it always
 * invokes the latest `fn`), so it is safe to list in effect dependency
 * arrays. Any pending invocation is cancelled on unmount.
 *
 * @param fn Callback to debounce; the latest render's value is invoked.
 * @param delayMs Trailing-edge delay in milliseconds.
 * @returns The debounced function, with `flush()` and `cancel()` attached.
 */
export function useDebouncedCallback<T extends (...args: never[]) => void>(
  fn: T,
  delayMs: number,
): DebouncedCallback<T> {
  const fnRef = useRef(fn);
  const delayRef = useRef(delayMs);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingArgsRef = useRef<Parameters<T> | null>(null);

  useEffect(() => {
    fnRef.current = fn;
    delayRef.current = delayMs;
  }, [fn, delayMs]);

  const debounced = useMemo(() => {
    const invoke = () => {
      timerRef.current = null;
      const args = pendingArgsRef.current;
      pendingArgsRef.current = null;
      if (args) fnRef.current(...args);
    };
    const wrapper = ((...args: Parameters<T>) => {
      pendingArgsRef.current = args;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(invoke, delayRef.current);
    }) as DebouncedCallback<T>;
    wrapper.cancel = () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = null;
      pendingArgsRef.current = null;
    };
    wrapper.flush = () => {
      if (timerRef.current === null) return;
      clearTimeout(timerRef.current);
      invoke();
    };
    return wrapper;
  }, []);

  useEffect(() => () => debounced.cancel(), [debounced]);

  return debounced;
}

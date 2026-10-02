import {useCallback, useEffect, useRef, useState} from 'react';
import {useLocation} from 'react-router-dom';

/**
 * Owns one history list's mount/navigation/event reload lifecycle. A loader
 * may return undefined to keep the current list after a transient failure.
 * Polling stays with the provider because only run history advances itself.
 */
export function useHistoryList<T>(
  load: () => Promise<T[] | undefined>,
  changedEvent: string,
) {
  const {pathname} = useLocation();
  const [items, setItems] = useState<T[]>([]);
  const mounted = useRef(false);
  const requestSequence = useRef(0);

  const reload = useCallback(async () => {
    if (!mounted.current) return;
    const request = ++requestSequence.current;
    const next = await load();
    if (
      mounted.current &&
      request === requestSequence.current &&
      next !== undefined
    ) {
      setItems(next);
    }
  }, [load]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, pathname]);

  useEffect(() => {
    window.addEventListener(changedEvent, reload);
    return () => window.removeEventListener(changedEvent, reload);
  }, [changedEvent, reload]);

  return {items, reload};
}

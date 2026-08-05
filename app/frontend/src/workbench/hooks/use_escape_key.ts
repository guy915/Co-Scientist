import {useEffect} from 'react';

/**
 * Window-level Escape-to-close: while `enabled`, an Escape keydown invokes
 * `onEscape`. The listener is attached only while enabled and removed again
 * on disable/unmount.
 *
 * @param onEscape Called when Escape is pressed.
 * @param enabled Whether the listener is attached at all.
 */
export function useEscapeKey(onEscape: () => void, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onEscape();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onEscape, enabled]);
}

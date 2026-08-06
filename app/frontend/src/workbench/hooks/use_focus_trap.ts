import {type RefObject, useEffect} from 'react';

// Everything Tab should be able to reach inside the trap. Matches the usual
// browser tab order (elements with a positive tabindex are rare enough in
// this codebase not to need special ordering here).
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  );
}

function includesActive(
  focusable: HTMLElement[],
  active: Element | null,
): boolean {
  return active !== null && focusable.includes(active as HTMLElement);
}

// True once Tab (forward) would otherwise leave the trap: focus already sits
// on the last focusable element, or somewhere outside the trap entirely
// (e.g. the trap's own root, which is deliberately not itself focusable).
function isAtOrPastLast(
  focusable: HTMLElement[],
  active: Element | null,
): boolean {
  return (
    active === focusable[focusable.length - 1] ||
    !includesActive(focusable, active)
  );
}

// The Shift+Tab mirror of isAtOrPastLast above.
function isAtOrPastFirst(
  focusable: HTMLElement[],
  active: Element | null,
): boolean {
  return active === focusable[0] || !includesActive(focusable, active);
}

/**
 * Given a trap's focusable elements, the currently active element, and
 * whether Shift is held, returns the element Tab should wrap focus to next
 * -- or null when the browser's own tab order already lands somewhere fine
 * (still inside the trap, not at either edge).
 */
export function nextTrapTarget(
  focusable: HTMLElement[],
  active: Element | null,
  shiftKey: boolean,
): HTMLElement | null {
  if (focusable.length === 0) return null;
  const wrapping = shiftKey
    ? isAtOrPastFirst(focusable, active)
    : isAtOrPastLast(focusable, active);
  if (!wrapping) return null;
  return shiftKey ? focusable[focusable.length - 1] : focusable[0];
}

/**
 * Traps Tab/Shift+Tab within `containerRef`'s subtree for as long as the
 * calling component stays mounted, so focus can't escape to the page behind
 * an open dialog. A container with no focusable descendants at all simply
 * blocks Tab from moving focus anywhere.
 *
 * @param containerRef The trap's boundary; only its subtree is ever queried
 *   or focused.
 */
export function useFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Tab') return;
      const container = containerRef.current;
      if (!container) return;
      const focusable = focusableElements(container);
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const target = nextTrapTarget(
        focusable,
        document.activeElement,
        event.shiftKey,
      );
      if (!target) return;
      event.preventDefault();
      target.focus();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [containerRef]);
}

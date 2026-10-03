import {type RefObject, useEffect, useRef} from 'react';

// Marks every OTHER child of `node`'s parent inert, and returns the elements
// it touched (so the caller can restore exactly those, not every inert
// element it happens to find later). Skips a sibling that is already inert
// -- from an outer ancestor's own siblings, or from a second dialog nested
// inside this one -- so restoring never un-inerts something this pass did
// not itself set.
function inertSiblingsOf(node: Element): Element[] {
  const parent = node.parentElement;
  if (!parent) return [];
  const touched: Element[] = [];
  for (const sibling of Array.from(parent.children)) {
    if (sibling === node || sibling.hasAttribute('inert')) continue;
    sibling.setAttribute('inert', '');
    touched.push(sibling);
  }
  return touched;
}

// Walks from `start` up to (not including) document.body, inerting every
// sibling along the way. Covers the element's own siblings whether it sits
// directly in the page's normal layout or several ancestors deep -- the
// element need not be portaled for this to reach everything around it.
function inertAncestorSiblings(start: Element): Element[] {
  const touched: Element[] = [];
  let node: Element | null = start;
  while (node && node !== document.body) {
    touched.push(...inertSiblingsOf(node));
    node = node.parentElement;
  }
  return touched;
}

/**
 * Makes everything outside `containerRef`'s element inert for as long as the
 * calling component stays mounted: background content can't be focused,
 * clicked, or read by assistive tech while a dialog sits over it. Restores
 * exactly the elements this hook itself marked, in case something else in
 * the page independently manages `inert` on one of the same nodes.
 *
 * jsdom does not implement `inert`'s behavioral effects (it does not block
 * focus or clicks), only the attribute itself -- tests can assert the
 * attribute's presence but not that it actually stops interaction.
 *
 * @param containerRef The dialog's own root; never itself marked inert.
 */
export function useBackgroundInert(
  containerRef: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const touched = inertAncestorSiblings(container);
    return () => {
      for (const element of touched) element.removeAttribute('inert');
    };
  }, [containerRef]);
}

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

// The opener and every ancestor above it, captured while the dialog opens.
// Only the opener itself is wanted, but it is routinely gone by the time the
// dialog closes -- the rail's Settings menu is a popover that unmounts the
// moment the dialog it launched appears, so the captured menu item is a
// detached node and `.focus()` on one is a silent no-op that drops focus to
// `<body>`. Measured in a browser: closing the dialog left
// `document.activeElement` as BODY, which restarts tabbing at the top of the
// page -- the exact disorientation restoring focus exists to prevent. The
// ancestor chain gives a landing spot that survives the popover.
function focusChain(start: Element | null): HTMLElement[] {
  const chain: HTMLElement[] = [];
  let node = start as HTMLElement | null;
  while (node) {
    chain.push(node);
    node = node.parentElement;
  }
  return chain;
}

// Focuses `target`, making it focusable first if it is a plain container
// (the fallback case: an ancestor that was never a control). Programmatic
// focus is the only way in, so `tabindex="-1"` keeps it out of the tab order.
function focusEvenIfInert(target: HTMLElement): void {
  target.focus();
  if (document.activeElement === target) return;
  target.setAttribute('tabindex', '-1');
  target.focus();
}

/**
 * Restores focus to whatever element held it just before this hook first
 * mounted, once the calling component unmounts -- however the dialog it
 * belongs to closed (Escape, a backdrop click, the close button, or the
 * first-visit affiliation gate answering itself and tearing the dialog
 * down). When the opener itself no longer exists, focus lands on the
 * nearest ancestor that does, rather than falling through to `<body>`.
 *
 * That fallback is a floor, not a bullseye: launched from the rail's
 * Settings menu, the whole popover is gone by the time the dialog closes and
 * the nearest survivor is the app shell, so the reader resumes tabbing from
 * the shell rather than from the trigger they actually used. Restoring the
 * trigger itself needs the component that owns it to hand one down; reading
 * it off `aria-expanded` was tried and does not work, because the menu has
 * already closed by the time this hook's mount effect runs.
 *
 * Call this before any other mount effect that moves focus into the dialog
 * (e.g. a focus-on-open effect). Effects run in the order their hooks are
 * declared, so declaring this one first is what lets the capture below see
 * the real opener rather than an element the dialog itself just focused.
 */
export function useRestoreFocusOnClose(): void {
  const chainRef = useRef<HTMLElement[]>([]);

  useEffect(() => {
    chainRef.current = focusChain(document.activeElement);
    return () => {
      const target = chainRef.current.find(el => el.isConnected);
      if (target) focusEvenIfInert(target);
    };
  }, []);
}

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

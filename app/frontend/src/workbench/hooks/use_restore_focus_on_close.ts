import {useEffect, useRef} from 'react';

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

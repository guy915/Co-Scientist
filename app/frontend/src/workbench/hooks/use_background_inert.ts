import {type RefObject, useEffect} from 'react';

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

/**
 * Scrolls an in-page section to the top of its nearest scroll container.
 *
 * Native hash navigation and scrollIntoView can no-op when the section is
 * already partially visible. This keeps section rails deterministic.
 *
 * @param sectionId The DOM id of the section element to scroll to.
 * @param offset Extra pixels to leave above the section (e.g. for sticky headers).
 * @returns True when the target element exists and a scroll was initiated.
 */
export function smoothScrollToSection(sectionId: string, offset = 0): boolean {
  const target = document.getElementById(sectionId);
  if (!target) return false;

  const container = findScrollContainer(target);
  if (container) {
    // Convert the target's viewport-relative position into a scrollTop for the
    // container: current scroll plus the on-screen delta between the two.
    const targetRect = target.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    container.scrollTo({
      top: container.scrollTop + targetRect.top - containerRect.top - offset,
      behavior: 'smooth',
    });
    return true;
  }

  // No scrollable ancestor found; fall back to native document scrolling
  // (offset is not applied on this path).
  target.scrollIntoView({behavior: 'smooth', block: 'start'});
  return true;
}

/**
 * Finds the ancestor element that actually scrolls the target: a known app
 * scroll pane when present, otherwise the nearest ancestor with a scrollable
 * overflow-y and real overflow.
 */
function findScrollContainer(target: HTMLElement): HTMLElement | null {
  // Known workbench scroll panes take priority over generic detection.
  const preferred = target.closest<HTMLElement>(
    '.idea-detail-pane, .cosci-report-scroll',
  );
  if (preferred) return preferred;

  // Generic fallback: walk up until an ancestor both allows vertical
  // scrolling and actually overflows.
  let current = target.parentElement;
  while (current) {
    const {overflowY} = getComputedStyle(current);
    if (
      /(auto|scroll|overlay)/.test(overflowY) &&
      current.scrollHeight > current.clientHeight
    ) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

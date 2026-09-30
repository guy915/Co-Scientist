/**
 * Scrolls an in-page section to the top of its nearest scroll container.
 *
 * Native hash navigation and scrollIntoView can no-op when the section is
 * already partially visible. This keeps section rails deterministic.
 *
 * @param sectionId The DOM id of the section element to scroll to.
 * @param offset Extra pixels to leave above the section (e.g. for sticky
 *   headers).
 * @param preferredSelector CSS selector for caller-known scroll panes to
 *   prefer over generic overflow detection (e.g. an app's report pane). When
 *   omitted, only the generic ancestor walk is used.
 * @param behavior 'smooth' by default; pass 'auto' to jump, e.g. under
 *   prefers-reduced-motion.
 * @returns True when the target element exists and a scroll was initiated.
 */
export function smoothScrollToSection(
  sectionId: string,
  offset = 0,
  preferredSelector?: string,
  behavior: ScrollBehavior = 'smooth',
): boolean {
  const target = document.getElementById(sectionId);
  if (!target) return false;

  const container = findScrollContainer(target, preferredSelector);
  if (container) {
    // Convert the target's viewport-relative position into a scrollTop for the
    // container: current scroll plus the on-screen delta between the two.
    const targetRect = target.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    container.scrollTo({
      top: container.scrollTop + targetRect.top - containerRect.top - offset,
      behavior,
    });
    return true;
  }

  // No scrollable ancestor found; fall back to native document scrolling
  // (offset is not applied on this path).
  target.scrollIntoView({behavior, block: 'start'});
  return true;
}

/** A caller-named scroll pane, when the target sits inside one. */
function findPreferredContainer(
  target: HTMLElement,
  preferredSelector?: string,
): HTMLElement | null {
  return preferredSelector
    ? target.closest<HTMLElement>(preferredSelector)
    : null;
}

/** Whether an element both allows vertical scrolling and actually overflows. */
function isScrollableOverflow(el: HTMLElement): boolean {
  const {overflowY} = getComputedStyle(el);
  return (
    /(auto|scroll|overlay)/.test(overflowY) && el.scrollHeight > el.clientHeight
  );
}

/**
 * Finds the ancestor element that actually scrolls the target: a
 * caller-named scroll pane when one matches, otherwise the nearest ancestor
 * with a scrollable overflow-y and real overflow.
 */
function findScrollContainer(
  target: HTMLElement,
  preferredSelector?: string,
): HTMLElement | null {
  // Caller-named scroll panes take priority over generic detection.
  const preferred = findPreferredContainer(target, preferredSelector);
  if (preferred) return preferred;

  // Generic fallback: walk up until an ancestor both allows vertical
  // scrolling and actually overflows.
  let current = target.parentElement;
  while (current) {
    if (isScrollableOverflow(current)) return current;
    current = current.parentElement;
  }
  return null;
}

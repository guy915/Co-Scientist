/**
 * Scrolls an in-page section to the top of its nearest scroll container.
 *
 * Native hash navigation and scrollIntoView can no-op when the section is
 * already partially visible. This keeps section rails deterministic.
 */
export function smoothScrollToSection(sectionId: string, offset = 0): boolean {
  const target = document.getElementById(sectionId);
  if (!target) return false;

  const container = findScrollContainer(target);
  if (container) {
    const targetRect = target.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    container.scrollTo({
      top: container.scrollTop + targetRect.top - containerRect.top - offset,
      behavior: 'smooth',
    });
    return true;
  }

  target.scrollIntoView({behavior: 'smooth', block: 'start'});
  return true;
}

function findScrollContainer(target: HTMLElement): HTMLElement | null {
  const preferred = target.closest<HTMLElement>(
    '.idea-detail-pane, .cosci-report-scroll',
  );
  if (preferred) return preferred;

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

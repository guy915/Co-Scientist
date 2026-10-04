import {useEffect, useState, useRef, type RefObject} from 'react';
import {logModalOpen} from '@/lib/ui_logging';

// One phone breakpoint prevents seams where related shell and workspace surfaces
// disagree on interaction mode.
export const MOBILE_MEDIA_QUERY = '(max-width: 700px)';

export function isMobileViewport(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia(MOBILE_MEDIA_QUERY).matches
  );
}

// Desktop rail state is a user preference; only an overlaying phone drawer
// should auto-collapse.
export function closeDrawerIfMobile(setNavOpen: (open: boolean) => void): void {
  if (isMobileViewport()) setNavOpen(false);
}

// createRoot mounts without hydration; synchronous initial measurement avoids a
// frame of incorrect desktop layout on phones.
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () =>
      typeof window.matchMedia === 'function' &&
      window.matchMedia(MOBILE_MEDIA_QUERY).matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(MOBILE_MEDIA_QUERY);
    const update = () => setIsMobile(mql.matches);
    // Viewport size can change between first render and subscribing; re-read
    // when installing the listener.
    update();
    mql.addEventListener('change', update);
    return () => mql.removeEventListener('change', update);
  }, []);
  return isMobile;
}

// Overflow containers clip tooltips even without scrolling; measure child span,
// not scrollHeight inflated by absolutely positioned tooltips.
export function useOverflowing<T extends HTMLElement>(): [
  React.RefObject<T | null>,
  boolean,
] {
  const ref = useRef<T>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const first = element.firstElementChild;
      const last = element.lastElementChild;
      if (!first || !last) {
        setOverflowing(false);
        return;
      }
      const span =
        last.getBoundingClientRect().bottom - first.getBoundingClientRect().top;
      // Fractional layout needs one-pixel slack to avoid permanent borderline
      // overflow.
      setOverflowing(span - element.clientHeight > 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.parentElement) observer.observe(element.parentElement);
    return () => {
      observer.disconnect();
    };
  });

  return [ref, overflowing];
}

// Before measurement, use minimum row height plus gap at the 16px root to keep
// first paint useful.
const FALLBACK_ROW_PITCH_PX = 43.2;

// Hidden or collapsed containers report zero height; retain a useful initial cap
// instead of shrinking to one row.
const UNMEASURED_ROW_COUNT = 10;

function measureRowPitch(rows: Element[]): number {
  if (rows.length >= 2) {
    const first = rows[0].getBoundingClientRect().top;
    const second = rows[1].getBoundingClientRect().top;
    const pitch = second - first;
    if (pitch > 0) return pitch;
  }
  if (rows.length === 1) {
    const height = rows[0].getBoundingClientRect().height;
    if (height > 0) return height;
  }
  return FALLBACK_ROW_PITCH_PX;
}

function fittingRowCount(container: Element, list: Element): number {
  const rows = [...list.children].filter(child =>
    child.hasAttribute('data-fitting-row'),
  );
  const pitch = measureRowPitch(rows);
  const available =
    container.getBoundingClientRect().bottom - list.getBoundingClientRect().top;
  if (available <= 0) return UNMEASURED_ROW_COUNT;
  // Always reserve the Show more slot so its appearance cannot push itself
  // offscreen or oscillate the row count.
  return Math.max(1, Math.floor(available / pitch) - 1);
}

// Measure the flexing container, not content-driven list height; data-fitting-
// row excludes the trailing Show more control.
export function useFittingRows<
  C extends HTMLElement,
  L extends HTMLElement,
>(): {
  containerRef: React.RefObject<C | null>;
  listRef: React.RefObject<L | null>;
  visibleCount: number;
} {
  const containerRef = useRef<C>(null);
  const listRef = useRef<L>(null);
  const [visibleCount, setVisibleCount] = useState(UNMEASURED_ROW_COUNT);

  // Rows load asynchronously, so every committed layout may provide a newly
  // measurable pitch.
  useEffect(() => {
    const container = containerRef.current;
    const list = listRef.current;
    if (!container || !list) return;
    const measure = () => setVisibleCount(fittingRowCount(container, list));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    observer.observe(list);
    return () => {
      observer.disconnect();
    };
  });

  return {containerRef, listRef, visibleCount};
}

// Restore only siblings this pass made inert; nested dialogs or independent
// owners may already control the others.
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

function inertAncestorSiblings(start: Element): Element[] {
  const touched: Element[] = [];
  let node: Element | null = start;
  while (node && node !== document.body) {
    touched.push(...inertSiblingsOf(node));
    node = node.parentElement;
  }
  return touched;
}

// jsdom implements inert attributes but not blocked interaction; tests can prove
// attributes, not browser behavior.
export function useBackgroundInert(
  containerRef: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const dialog = container.matches('[role="dialog"]')
      ? container
      : container.querySelector('[role="dialog"]');
    logModalOpen(dialog?.getAttribute('aria-label') ?? 'Dialog');
    const touched = inertAncestorSiblings(container);
    return () => {
      for (const element of touched) element.removeAttribute('inert');
    };
  }, [containerRef]);
}

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

// The opener’s popover can unmount before close; capture surviving ancestors so
// restoring focus does not silently fall back to body.
function focusChain(start: Element | null): HTMLElement[] {
  const chain: HTMLElement[] = [];
  let node = start as HTMLElement | null;
  while (node) {
    chain.push(node);
    node = node.parentElement;
  }
  return chain;
}

// Fallback containers need programmatic focus without becoming ordinary Tab
// stops.
function focusEvenIfInert(target: HTMLElement): void {
  target.focus();
  if (document.activeElement === target) return;
  target.setAttribute('tabindex', '-1');
  target.focus();
}

// Capture before any mount effect moves focus; restore a surviving ancestor when
// the original opener has unmounted.
export function useRestoreFocusOnClose(): void {
  const chainRef = useRef<HTMLElement[]>([]);

  useEffect(() => {
    if (!chainRef.current.length) {
      chainRef.current = focusChain(document.activeElement);
    }
    return () => {
      const target = chainRef.current.find(el => el.isConnected);
      if (!target) return;
      // Sibling inert cleanup may run after this effect. Restore after that
      // cleanup rather than changing tabindex on a still-blocked opener.
      if (target.closest('[inert]')) {
        queueMicrotask(() => {
          if (target.isConnected && !target.closest('[inert]')) {
            focusEvenIfInert(target);
          }
        });
      } else {
        focusEvenIfInert(target);
      }
    };
  }, []);
}

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

function isAtOrPastLast(
  focusable: HTMLElement[],
  active: Element | null,
): boolean {
  return (
    active === focusable[focusable.length - 1] ||
    !includesActive(focusable, active)
  );
}

function isAtOrPastFirst(
  focusable: HTMLElement[],
  active: Element | null,
): boolean {
  return active === focusable[0] || !includesActive(focusable, active);
}

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

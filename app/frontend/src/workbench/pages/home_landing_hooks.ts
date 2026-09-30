// Small DOM hooks shared by the landing page's sections.

import {type RefObject, useEffect, useState} from 'react';

/** Props every animated landing section takes. */
export interface MotionProps {
  reduceMotion: boolean;
}

const REDUCE_QUERY = '(prefers-reduced-motion: reduce)';

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia(REDUCE_QUERY).matches
  );
}

/** Tracks the OS reduced-motion preference. */
export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(prefersReducedMotion);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(REDUCE_QUERY);
    const onChange = () => setReduce(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  return reduce;
}

/**
 * Reports whether the referenced element is on screen. With `once`, it
 * latches true the first time the element appears, which is what entrance
 * animations want; without it, it follows visibility, which is what a
 * running animation wants so it can pause off screen. Where the browser has
 * no IntersectionObserver it reports false, so nothing animates.
 */
export function useInView(
  ref: RefObject<Element | null>,
  {once = true, margin = '0px', threshold = 0.15} = {},
): boolean {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (once && !entry.isIntersecting) return;
        setInView(entry.isIntersecting);
        if (once) observer.disconnect();
      },
      {rootMargin: margin, threshold},
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, once, margin, threshold]);
  return inView;
}

/**
 * Returns the nearest ancestor of `el` that scrolls vertically, or the
 * window when the document itself is the scroller. The home page scrolls
 * inside the shell's page element, not the window, so scroll listeners and
 * scroll-to-top calls must target whichever this is.
 */
export function scrollParent(el: Element | null): HTMLElement | Window {
  for (let node = el?.parentElement; node; node = node.parentElement) {
    const {overflowY} = getComputedStyle(node);
    if (overflowY === 'auto' || overflowY === 'scroll') return node;
  }
  return window;
}

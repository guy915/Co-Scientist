import {useEffect, useRef, useState} from 'react';

/**
 * Tracks whether an element's children are taller than the room it has.
 *
 * Lets a list stay a plain box until it actually needs to scroll. That
 * matters for anything carrying CSS tooltips: a scroll container clips its
 * content to the padding box whether or not a scrollbar is showing, so an
 * unconditional `overflow-y: auto` cuts off tooltips even when there is
 * nothing to scroll.
 *
 * Measures the span of the children rather than `scrollHeight`, which counts
 * absolutely positioned descendants: a hidden tooltip hanging below the last
 * child inflates `scrollHeight` past the box, which would report a list that
 * fits as overflowing, clip it, and hide the very tooltips being measured.
 * The span is also independent of how far the element happens to be scrolled,
 * since both edges move together.
 *
 * @returns A ref to attach to the element, and whether it currently overflows.
 */
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
      // Sub-pixel layout leaves fractional slack, so allow a pixel rather than
      // reporting a permanent one-pixel overflow.
      setOverflowing(span - element.clientHeight > 1);
    };
    measure();
    // Watch the element (its content changing) and the parent that bounds it,
    // since the rail's height is what decides whether the list still fits.
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.parentElement) observer.observe(element.parentElement);
    return () => {
      observer.disconnect();
    };
  });

  return [ref, overflowing];
}

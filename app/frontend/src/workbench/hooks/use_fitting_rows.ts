import {useEffect, useRef, useState} from 'react';

/**
 * Row pitch assumed before anything has been measured: the chat link's
 * 2.35rem minimum height plus the list's 0.35rem gap at a 16px root. Only
 * used for the first paint and for an empty list, where there is no rendered
 * row to measure.
 */
const FALLBACK_ROW_PITCH_PX = 43.2;

/**
 * Rows shown before the container has a measurable height: a collapsed rail,
 * a hidden drawer, and a test renderer all report zero, and collapsing the
 * list to a single row there would be a worse answer than the cap this
 * replaced.
 */
const UNMEASURED_ROW_COUNT = 10;

/** The distance between consecutive rows, including the list's gap. */
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

/**
 * How many rows fit between the list's top and the container's bottom, with
 * one pitch held back for the "Show more" control that sits under them.
 */
function fittingRowCount(container: Element, list: Element): number {
  const rows = [...list.children].filter(child =>
    child.hasAttribute('data-fitting-row'),
  );
  const pitch = measureRowPitch(rows);
  const available =
    container.getBoundingClientRect().bottom - list.getBoundingClientRect().top;
  if (available <= 0) return UNMEASURED_ROW_COUNT;
  // The row count the space affords, less the slot the "Show more" button
  // occupies -- reserving it unconditionally keeps the button from being the
  // thing pushed out of view, and keeps the count from oscillating as the
  // button appears and disappears with it.
  return Math.max(1, Math.floor(available / pitch) - 1);
}

/**
 * Tracks how many list rows fit in the space their container actually has.
 *
 * The rail's chat list used to show a hardcoded ten, which left a tall
 * window half empty and a short one scrolling. The measurement is taken
 * from the container that flexes (not the list, whose height is its own
 * content) down to the list's top edge, so a heading or margin above the
 * rows is accounted for without being named here.
 *
 * Rows must carry `data-fitting-row` so the trailing "Show more" control is
 * not measured as one of them.
 *
 * @returns Refs for the flexing container and the row list, plus the number
 *   of rows that currently fit.
 */
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

  // No dependency array: rows change as the chat list loads, and the pitch
  // can only be measured from what is currently rendered.
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

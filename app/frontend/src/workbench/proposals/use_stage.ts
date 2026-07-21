import {useCallback, useLayoutEffect, useState} from 'react';
import type {Stage} from './proposals_layout';

const EMPTY: Stage = {width: 0, height: 0};

/**
 * Measures the space the graph has to fill. The layout is sized to this
 * rather than scaled into it, so the measurement is its input.
 *
 * @returns A ref callback for the stage element and its current size.
 */
export function useStage(): [(node: HTMLElement | null) => void, Stage] {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [stage, setStage] = useState<Stage>(EMPTY);

  const measure = useCallback((node: HTMLElement) => {
    const box = node.getBoundingClientRect();
    // Rounded, so sub-pixel jitter cannot count as a size change: every
    // change that passes the bailout below re-runs the full layout.
    const width = Math.round(box.width);
    const height = Math.round(box.height);
    setStage(current =>
      current.width === width && current.height === height
        ? current
        : {width, height},
    );
  }, []);

  useLayoutEffect(() => {
    if (!element) return;
    measure(element);
    // Catches the window resizing and the detail panel opening beside it.
    // A drag fires the observer faster than the layout is worth recomputing,
    // so observations coalesce to one measurement per frame.
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => measure(element));
    });
    observer.observe(element);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [element, measure]);

  return [setElement, stage];
}

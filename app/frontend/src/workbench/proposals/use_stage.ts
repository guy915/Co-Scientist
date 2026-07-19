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
    setStage(current =>
      current.width === box.width && current.height === box.height
        ? current
        : {width: box.width, height: box.height},
    );
  }, []);

  useLayoutEffect(() => {
    if (!element) return;
    measure(element);
    // Catches the window resizing and the detail panel opening beside it.
    const observer = new ResizeObserver(() => measure(element));
    observer.observe(element);
    return () => observer.disconnect();
  }, [element, measure]);

  return [setElement, stage];
}

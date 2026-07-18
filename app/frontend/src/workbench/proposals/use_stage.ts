import {useCallback, useLayoutEffect, useState} from 'react';
import type {Stage} from './proposals_layout';

const EMPTY: Stage = {width: 0, height: 0, legendLeft: 0, legendRight: 0};

/**
 * Measures the space the graph has: the stage itself, and how much of its
 * width each legend card takes. The layout is computed from real pixels
 * rather than scaled into place, so those measurements are the input.
 *
 * @param legendsShown Whether the legend cards are currently rendered. The
 *   stage does not resize when they mount or unmount, so their presence has
 *   to re-trigger the measurement explicitly.
 * @returns A ref callback for the stage element and its current metrics.
 */
export function useStage(
  legendsShown: boolean,
): [(node: HTMLElement | null) => void, Stage] {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [stage, setStage] = useState<Stage>(EMPTY);

  const measure = useCallback((node: HTMLElement) => {
    const box = node.getBoundingClientRect();
    // A legend is only an obstacle while it is on screen; when a proposal is
    // open they are hidden and the top row gets the full width.
    const card = (selector: string) =>
      node.querySelector(selector)?.getBoundingClientRect().width ?? 0;
    const next: Stage = {
      width: box.width,
      height: box.height,
      legendLeft: card('.proposals-legend.is-categories'),
      legendRight: card('.proposals-legend.is-relationships'),
    };
    setStage(current =>
      current.width === next.width &&
      current.height === next.height &&
      current.legendLeft === next.legendLeft &&
      current.legendRight === next.legendRight
        ? current
        : next,
    );
  }, []);

  useLayoutEffect(() => {
    if (!element) return;
    measure(element);
    // Catches the window resizing, the panel opening beside the graph, and
    // the legends appearing or disappearing.
    const observer = new ResizeObserver(() => measure(element));
    observer.observe(element);
    for (const card of element.querySelectorAll('.proposals-legend')) {
      observer.observe(card);
    }
    return () => observer.disconnect();
  }, [element, measure, legendsShown]);

  return [setElement, stage];
}

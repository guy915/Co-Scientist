// Which side of the anchor the tooltip bubble appears on.
type TooltipPlacement = 'top' | 'right' | 'bottom' | 'left';

interface TooltipClassOptions {
  className?: string; // the anchor's own classes, prepended verbatim
  placement: TooltipPlacement;
  wrap?: boolean; // allow multi-line tooltips (defaults to nowrap)
  alignEnd?: boolean; // align the bubble to the anchor's end edge
  alignStart?: boolean; // align the bubble to the anchor's start edge
}

/**
 * Builds the class list that turns an element into a CSS-only tooltip anchor.
 *
 * The tooltip itself is pure CSS (styles/tooltips.css renders it as an
 * ::after pseudo-element from the anchor's `data-tooltip` attribute) -- there
 * is no tooltip component or JS positioning. Callers merge their own classes
 * via `className` and must set `data-tooltip` on the same element.
 *
 * @returns The combined class string for the anchor element.
 */
export function tooltipClassNames({
  className,
  placement,
  wrap,
  alignEnd,
  alignStart,
}: TooltipClassOptions): string {
  return [
    className,
    'ucs-tooltip-anchor',
    `ucs-tooltip-${placement}`,
    wrap ? 'ucs-tooltip-wrap' : 'ucs-tooltip-nowrap',
    alignEnd ? 'ucs-tooltip-align-end' : '',
    alignStart ? 'ucs-tooltip-align-start' : '',
  ]
    .filter(Boolean)
    .join(' ');
}

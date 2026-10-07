import type {ReactNode} from 'react';
import {joinClasses} from './cx';

export type TooltipPlacement = 'top' | 'right' | 'bottom' | 'left';

export interface TooltipOptions {
  placement?: TooltipPlacement;
  // Long text wraps at a reading width instead of one line.
  wrap?: boolean;
  // Anchors wider than their tooltip align it to their start edge.
  alignStart?: boolean;
}

// The tooltip is the anchor's own ::after (styles/tooltips.css), so it shows on
// hover and keyboard focus without a portal or a listener.
export function tooltipClassNames({
  className,
  placement = 'top',
  wrap,
  alignStart,
}: TooltipOptions & {className?: string}): string {
  return joinClasses(
    className,
    'ucs-tooltip-anchor',
    `ucs-tooltip-${placement}`,
    wrap ? 'ucs-tooltip-wrap' : 'ucs-tooltip-nowrap',
    alignStart && 'ucs-tooltip-align-start',
  );
}

// Spread onto a focusable element that should carry a tooltip.
export function tooltipProps(
  text: string,
  options: TooltipOptions & {className?: string} = {},
): {className: string; 'data-tooltip': string} {
  return {className: tooltipClassNames(options), 'data-tooltip': text};
}

// Wraps non-interactive content (a status chip, a truncated label) that needs a
// tooltip; interactive controls take `tooltip` on Button or IconButton instead.
export function Tooltip({
  content,
  children,
  className,
  ...options
}: TooltipOptions & {
  content: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span {...tooltipProps(content, {...options, className})}>{children}</span>
  );
}

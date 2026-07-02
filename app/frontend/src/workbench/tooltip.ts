type TooltipPlacement = 'top' | 'right' | 'bottom';

type TooltipClassOptions = {
  className?: string;
  placement: TooltipPlacement;
  wrap?: boolean;
  alignEnd?: boolean;
  alignStart?: boolean;
};

export function tooltipClassNames({
  className,
  placement,
  wrap = false,
  alignEnd = false,
  alignStart = false,
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

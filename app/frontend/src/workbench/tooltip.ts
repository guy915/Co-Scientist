type TooltipPlacement = 'top' | 'right';

type TooltipClassOptions = {
  className?: string;
  placement: TooltipPlacement;
  wrap?: boolean;
  alignEnd?: boolean;
};

export function tooltipClassNames({
  className,
  placement,
  wrap = false,
  alignEnd = false,
}: TooltipClassOptions): string {
  return [
    className,
    'ucs-tooltip-anchor',
    `ucs-tooltip-${placement}`,
    wrap ? 'ucs-tooltip-wrap' : 'ucs-tooltip-nowrap',
    alignEnd ? 'ucs-tooltip-align-end' : '',
  ]
    .filter(Boolean)
    .join(' ');
}

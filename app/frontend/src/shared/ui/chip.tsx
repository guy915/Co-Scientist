import type {HTMLAttributes, ReactNode} from 'react';
import {Icon, type IconName} from './icon';
import {joinClasses} from './cx';
import {tooltipClassNames, type TooltipPlacement} from './tooltip';

export type ChipTone =
  'neutral' | 'info' | 'success' | 'accent' | 'warning' | 'danger';
export type ChipVariant = 'tonal' | 'outlined';
export type ChipSize = 'xs' | 'sm' | 'md';

const TONAL_CLASSES: Record<ChipTone, string> = {
  neutral: 'bg-chip-neutral-bg text-chip-neutral-fg',
  info: 'bg-chip-info-bg text-chip-info-fg',
  success: 'bg-chip-success-bg text-chip-success-fg',
  accent: 'bg-chip-accent-bg text-chip-accent-fg',
  warning: 'bg-chip-warning-bg text-chip-warning-fg',
  danger: 'bg-chip-danger-bg text-chip-danger-fg',
};

const OUTLINED_CLASSES: Record<ChipTone, string> = {
  neutral: 'border-cosci-border text-cosci-muted',
  info: 'border-cosci-border text-chip-info-fg',
  success: 'border-cosci-border text-chip-success-fg',
  accent: 'border-chip-accent-bg text-chip-accent-bg',
  warning: 'border-chip-warning-fg text-chip-warning-fg',
  danger: 'border-chip-danger-border bg-chip-danger-bg text-chip-danger-fg',
};

const SIZE_CLASSES: Record<ChipSize, string> = {
  xs: 'min-h-[1.45rem] gap-1 px-2 text-[0.6875rem] font-medium',
  sm: 'h-[1.7rem] gap-1 px-2.5 text-[0.72rem] font-semibold',
  md: 'h-7 gap-1 px-3 text-[0.8rem] font-medium',
};

const ICON_CLASSES: Record<ChipSize, string> = {
  xs: 'text-[0.8rem]',
  sm: 'text-[0.95rem]',
  md: 'text-[1rem]',
};

export interface ChipStyle {
  tone?: ChipTone;
  variant?: ChipVariant;
  size?: ChipSize;
  // A chip that is itself a link gets a hover and focus state.
  interactive?: boolean;
}

// Chips are always pills; anchors that read as chips use these classes.
export function chipClasses({
  tone = 'neutral',
  variant = 'tonal',
  size = 'md',
  interactive = false,
}: ChipStyle = {}): string {
  return joinClasses(
    'inline-flex w-fit items-center rounded-full whitespace-nowrap no-underline',
    variant === 'outlined'
      ? `border bg-transparent ${OUTLINED_CLASSES[tone]}`
      : `border-0 ${TONAL_CLASSES[tone]}`,
    SIZE_CLASSES[size],
    interactive &&
      'cursor-pointer hover:border-cosci-muted hover:bg-cosci-hover ' +
        'focus-visible:outline-2 focus-visible:outline-offset-2 ' +
        'focus-visible:outline-th-ring',
  );
}

export function chipIconClasses(size: ChipSize = 'md'): string {
  return ICON_CLASSES[size];
}

export function Chip({
  tone,
  variant,
  size = 'md',
  icon,
  tooltip,
  tooltipPlacement = 'top',
  layoutClassName,
  children,
  ...rest
}: Omit<ChipStyle, 'interactive'> &
  Omit<HTMLAttributes<HTMLSpanElement>, 'className'> & {
    icon?: IconName;
    tooltip?: string;
    tooltipPlacement?: TooltipPlacement;
    layoutClassName?: string;
    children: ReactNode;
  }) {
  const className = joinClasses(
    chipClasses({tone, variant, size}),
    layoutClassName,
  );
  return (
    <span
      className={
        tooltip
          ? tooltipClassNames({
              className,
              placement: tooltipPlacement,
              wrap: true,
            })
          : className
      }
      data-tooltip={tooltip}
      {...rest}
    >
      {icon && <Icon className={ICON_CLASSES[size]} name={icon} />}
      {children}
    </span>
  );
}

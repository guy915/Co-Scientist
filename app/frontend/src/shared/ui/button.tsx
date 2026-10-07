import type {ButtonHTMLAttributes, ReactNode, Ref} from 'react';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from './cx';
import {tooltipClassNames, type TooltipPlacement} from './tooltip';

export type ButtonVariant = 'filled' | 'outlined' | 'tonal' | 'text' | 'link';
export type ButtonSize = 'sm' | 'md' | 'lg';

// Shape, focus ring and state colours live here so no call site restyles a
// button. No preflight runs, so the UA border and padding are reset too.
const BASE_CLASSES =
  'inline-flex cursor-pointer items-center justify-center rounded-full border ' +
  'font-[inherit] whitespace-nowrap no-underline select-none ' +
  'disabled:cursor-default focus-visible:outline-2 ' +
  'focus-visible:outline-offset-2 focus-visible:outline-th-ring';

const DISABLED_CLASSES =
  'disabled:border-button-disabled-border disabled:bg-button-disabled-bg ' +
  'disabled:text-button-disabled-fg';

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  filled:
    'border-button-filled-bg bg-button-filled-bg text-button-filled-fg ' +
    `enabled:hover:bg-button-filled-hover ${DISABLED_CLASSES}`,
  outlined:
    'border-button-outlined-border bg-transparent text-button-outlined-fg ' +
    `enabled:hover:bg-button-outlined-hover ${DISABLED_CLASSES}`,
  tonal:
    'border-transparent bg-button-tonal-bg text-button-tonal-fg ' +
    'enabled:hover:bg-button-tonal-hover aria-expanded:bg-button-tonal-hover ' +
    DISABLED_CLASSES,
  text:
    'border-transparent bg-transparent text-button-text-fg ' +
    'enabled:hover:bg-button-text-hover-bg enabled:hover:text-button-text-hover-fg ' +
    'disabled:text-button-disabled-fg',
  link:
    'border-transparent bg-transparent text-button-link-fg underline-offset-2 ' +
    'enabled:hover:underline disabled:text-button-disabled-fg',
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'min-h-[2.35rem] gap-[0.45rem] px-[0.85rem] text-[0.875rem] font-semibold',
  md: 'min-h-[2.6rem] gap-2 px-[1.45rem] font-medium',
  lg: 'min-h-12 gap-2 px-6 text-base font-medium',
};

// Link buttons sit inline with text, so they keep the text's own height.
const LINK_SIZE_CLASSES = 'gap-1 px-1 py-0.5 font-medium';

const ICON_CLASSES: Record<ButtonSize, string> = {
  sm: 'text-[1.05rem]',
  md: 'text-[1.15rem]',
  lg: 'text-[1.25rem]',
};

export interface ButtonStyle {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

// For router links and anchors that look like buttons.
export function buttonClasses({
  variant = 'filled',
  size = 'md',
}: ButtonStyle = {}): string {
  return joinClasses(
    BASE_CLASSES,
    VARIANT_CLASSES[variant],
    variant === 'link' ? LINK_SIZE_CLASSES : SIZE_CLASSES[size],
  );
}

export function buttonIconClasses(size: ButtonSize = 'md'): string {
  return joinClasses('flex-none', ICON_CLASSES[size]);
}

export interface ButtonProps
  extends
    ButtonStyle,
    Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  icon?: IconName;
  trailingIcon?: IconName;
  tooltip?: string;
  tooltipPlacement?: TooltipPlacement;
  // Layout only (margins, grid placement, width); never colour or shape.
  layoutClassName?: string;
  ref?: Ref<HTMLButtonElement>;
  children?: ReactNode;
}

export function Button({
  variant,
  size = 'md',
  icon,
  trailingIcon,
  tooltip,
  tooltipPlacement = 'top',
  layoutClassName,
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  const className = joinClasses(
    buttonClasses({variant, size}),
    layoutClassName,
  );
  return (
    <button
      type={type}
      className={
        tooltip
          ? tooltipClassNames({className, placement: tooltipPlacement})
          : className
      }
      data-tooltip={tooltip}
      {...rest}
    >
      {icon && (
        <Icon
          aria-hidden="true"
          className={buttonIconClasses(size)}
          name={icon}
        />
      )}
      {children}
      {trailingIcon && (
        <Icon
          aria-hidden="true"
          className={buttonIconClasses(size)}
          name={trailingIcon}
        />
      )}
    </button>
  );
}

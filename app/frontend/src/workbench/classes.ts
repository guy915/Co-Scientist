export function joinClasses(
  ...classes: (string | false | null | undefined)[]
): string {
  return classes.filter(Boolean).join(' ');
}

export function tooltipClassNames({
  className,
  placement,
  wrap,
  alignStart,
}: {
  className?: string;
  placement: 'top' | 'right' | 'bottom' | 'left';
  wrap?: boolean;
  alignStart?: boolean;
}): string {
  return joinClasses(
    className,
    'ucs-tooltip-anchor',
    `ucs-tooltip-${placement}`,
    wrap ? 'ucs-tooltip-wrap' : 'ucs-tooltip-nowrap',
    alignStart && 'ucs-tooltip-align-start',
  );
}

export const COMPOSER_SOURCE_ICON_CLASSES = 'text-xl';
export const SETUP_SECONDARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-cosci-btn-secondary-border bg-transparent px-[1.45rem] font-medium text-cosci-btn-secondary-fg hover:bg-cosci-btn-secondary-hover-bg focus-visible:bg-cosci-btn-secondary-hover-bg disabled:cursor-default disabled:border-cosci-btn-disabled-border disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';
export const OPTION_MARKER_CLASSES =
  'mt-[0.08rem] size-[1.28rem] rounded-full border-2 border-cosci-option-marker';
export const OPTION_MARKER_SELECTED_CLASSES =
  'border-cosci-option-marker-on bg-[radial-gradient(circle,var(--cosci-blue)_0_42%,transparent_44%)]';
export const OPTION_INPUT_CLASSES = 'absolute pointer-events-none opacity-0';
export const OPTION_LABEL_CLASSES = 'min-w-0 text-base leading-[1.2] font-bold';
export const SETUP_ACTIONS_CLASSES =
  'reference-setup-actions flex flex-wrap justify-end gap-[0.7rem] pt-[0.3rem] [&>button]:whitespace-nowrap';
export const SETUP_PRIMARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-cosci-btn-primary-bg bg-cosci-btn-primary-bg px-[1.45rem] font-medium text-cosci-btn-primary-fg hover:bg-cosci-btn-primary-hover focus-visible:bg-cosci-btn-primary-hover disabled:cursor-default disabled:border-cosci-btn-disabled-border disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';
export const OPTION_GROUP_CLASSES =
  'reference-option-group m-0 grid min-w-0 gap-[0.9rem] border-0 p-0';
export const OPTION_GROUP_LEGEND_CLASSES =
  'text-[1.18rem] font-bold text-cosci-fg';

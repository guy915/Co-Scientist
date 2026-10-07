// Re-exported while call sites move to the shared building blocks.
export {joinClasses} from '@/shared/ui/cx';
export {tooltipClassNames} from '@/shared/ui/tooltip';

export const SETTINGS_SCRIM_CLASSES =
  'fixed inset-0 z-[70] bg-[rgb(0_0_0/45%)]';
// Settings and Feedback share this surface; each adds its own size and padding.
export const SETTINGS_DIALOG_CLASSES =
  'fixed top-1/2 left-1/2 z-[71] flex flex-col rounded-[1.75rem] bg-cosci-menu-bg text-cosci-fg [transform:translate(-50%,-50%)] [@media(max-width:700px)]:rounded-[1.25rem]';
export const SETTINGS_DIALOG_TITLE_CLASSES =
  'm-0 font-gsans text-[1.375rem] font-medium tracking-[-0.01em]';
export const SETTINGS_FIELD_LABEL_CLASSES =
  'mb-[0.45rem] text-[0.875rem] font-medium';
export const SETTINGS_FIELD_CLASSES =
  'w-full rounded-xl border border-cosci-border bg-cosci-menu-bg px-[0.9rem] py-[0.65rem] text-[0.9rem] text-cosci-fg focus-visible:border-cosci-blue focus-visible:outline-1 focus-visible:outline-cosci-blue focus-visible:outline-offset-0';

export const SETUP_SECONDARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-cosci-btn-secondary-border bg-transparent px-[1.45rem] font-medium text-cosci-btn-secondary-fg hover:bg-cosci-btn-secondary-hover-bg focus-visible:bg-cosci-btn-secondary-hover-bg disabled:cursor-default disabled:border-cosci-btn-disabled-border disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';
export const OPTION_MARKER_CLASSES =
  'mt-[0.08rem] size-[1.28rem] rounded-full border-2 border-cosci-option-marker';
export const OPTION_MARKER_SELECTED_CLASSES =
  'border-cosci-option-marker-on bg-[radial-gradient(circle,var(--cosci-blue)_0_42%,transparent_44%)]';

export const SETUP_ACTIONS_CLASSES =
  'reference-setup-actions flex flex-wrap justify-end gap-[0.7rem] pt-[0.3rem] [&>button]:whitespace-nowrap';
export const SETUP_PRIMARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-cosci-btn-primary-bg bg-cosci-btn-primary-bg px-[1.45rem] font-medium text-cosci-btn-primary-fg hover:bg-cosci-btn-primary-hover focus-visible:bg-cosci-btn-primary-hover disabled:cursor-default disabled:border-cosci-btn-disabled-border disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';

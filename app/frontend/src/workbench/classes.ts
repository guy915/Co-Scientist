// Re-exported while call sites move to the shared building blocks.
export {joinClasses} from '@/shared/ui/cx';
export {tooltipClassNames} from '@/shared/ui/tooltip';

export const SETTINGS_SCRIM_CLASSES =
  'fixed inset-0 z-[70] bg-[rgb(0_0_0/45%)]';
// Settings and Feedback share this surface; each adds its own size and padding.
// Its background equals the default hover tone in dark mode, so the surface
// re-points the hover tokens.
export const SETTINGS_DIALOG_CLASSES =
  '[--button-outlined-hover:var(--cosci-menu-row-hover)] [--icon-button-hover-bg:var(--cosci-menu-row-hover)] fixed top-1/2 left-1/2 z-[71] flex flex-col rounded-[1.75rem] bg-cosci-menu-bg text-cosci-fg [transform:translate(-50%,-50%)] [@media(max-width:700px)]:rounded-[1.25rem]';
export const SETTINGS_DIALOG_TITLE_CLASSES =
  'm-0 font-gsans text-[1.375rem] font-medium tracking-[-0.01em]';
export const SETTINGS_FIELD_LABEL_CLASSES =
  'mb-[0.45rem] text-[0.875rem] font-medium';
export const SETTINGS_FIELD_CLASSES =
  'w-full rounded-xl border border-cosci-border bg-cosci-menu-bg px-[0.9rem] py-[0.65rem] text-[0.9rem] text-cosci-fg focus-visible:border-cosci-blue focus-visible:outline-1 focus-visible:outline-cosci-blue focus-visible:outline-offset-0';

export const OPTION_MARKER_CLASSES =
  'mt-[0.08rem] size-[1.28rem] rounded-full border-2 border-cosci-option-marker';
export const OPTION_MARKER_SELECTED_CLASSES =
  'border-cosci-option-marker-on bg-[radial-gradient(circle,var(--cosci-blue)_0_42%,transparent_44%)]';

export const SETUP_ACTIONS_CLASSES =
  'reference-setup-actions flex flex-wrap justify-end gap-[0.7rem] pt-[0.3rem] [&>button]:whitespace-nowrap';

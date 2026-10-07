// Re-exported while call sites move to the shared building blocks.
export {joinClasses} from '@/shared/ui/cx';
export {tooltipClassNames} from '@/shared/ui/tooltip';

export const SETTINGS_FIELD_LABEL_CLASSES =
  'mb-[0.45rem] text-[0.875rem] font-medium';

export const OPTION_MARKER_CLASSES =
  'mt-[0.08rem] size-[1.28rem] rounded-full border-2 border-cosci-option-marker';
export const OPTION_MARKER_SELECTED_CLASSES =
  'border-cosci-option-marker-on bg-[radial-gradient(circle,var(--cosci-blue)_0_42%,transparent_44%)]';

export const SETUP_ACTIONS_CLASSES =
  'reference-setup-actions flex flex-wrap justify-end gap-[0.7rem] pt-[0.3rem] [&>button]:whitespace-nowrap';

// Class strings for the home surface, which reproduces the Gemini reference
// 1:1. Any arbitrary rem values here are literal measurements copied from the
// reference and do NOT follow the app's 8px grid — that grid governs MD3 data
// surfaces only. See DESIGN.md > Layout & Spacing ("Reference-matched surfaces
// do not use the 8px grid").

export const HOME_WORKSPACE_CLASSES = 'reference-workspace';

export const HOME_WORKSPACE_MAIN_CLASSES = 'reference-workspace-main';

export const HOME_STAGE_CLASSES = 'reference-home-stage';

export const HOME_MAIN_CLASSES = 'reference-home-main';

export const HOME_AGENT_CHIP_CLASSES = 'reference-agent-chip';

export const HOME_AGENT_CHIP_ICON_CLASSES = 'reference-agent-chip-icon';

export const HOME_TITLE_CLASSES = 'reference-home-title';

export const HOME_STEP_TIMELINE_CLASSES = 'reference-step-timeline';

export const HOME_STEP_ITEM_CLASSES = 'reference-step-item';

export const HOME_STEP_ITEM_CENTER_CLASSES = 'reference-step-item--center';

export const HOME_STEP_ITEM_END_CLASSES = 'reference-step-item--end';

export const HOME_STEP_BODY_CLASSES = 'reference-step-body';

export const HOME_STEP_NUMBER_CLASSES = 'reference-step-number';

export const HOME_STEP_HEADING_CLASSES = 'reference-step-heading';

export const HOME_SUGGESTION_ROW_CLASSES = 'reference-suggestion-row';

export const HOME_SUGGESTION_BUTTON_CLASSES = 'reference-suggestion-button';

export const HOME_SUGGESTION_BUTTON_PREVIEWED_CLASSES = 'is-previewed';

export const HOME_SUGGESTION_SLOT_CLASSES = 'reference-suggestion-slot';

export const HOME_SUGGESTION_PREVIEW_CLASSES = 'reference-suggestion-preview';

export const HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES = 'visible';

export const HOME_SUGGESTION_PREVIEW_START_CLASSES =
  'reference-suggestion-preview--start';

export const HOME_SUGGESTION_PREVIEW_CENTER_CLASSES =
  'reference-suggestion-preview--center';

export const HOME_SUGGESTION_PREVIEW_END_CLASSES =
  'reference-suggestion-preview--end';

export const HOME_SUGGESTION_TEXT_CLASSES = 'reference-suggestion-text';

export const HOME_COMPOSER_CLASSES = 'reference-home-composer';

export const HOME_COMPOSER_TEXTAREA_CLASSES =
  'reference-home-composer-textarea';

export const HOME_RECENTS_PANEL_CLASSES = 'reference-recents-panel';

export const HOME_RECENTS_LIST_CLASSES = 'reference-recents-list';

export const HOME_RECENTS_HEADING_ROW_CLASSES = 'reference-recents-heading';

export const HOME_LOAD_MORE_ITEM_CLASSES = 'reference-load-more-item';

export const HOME_LOAD_MORE_BUTTON_CLASSES = 'reference-load-more';

export const HOME_TOAST_CLASSES =
  'reference-toast fixed top-1/2 left-1/2 z-[60] -translate-x-1/2 ' +
  '-translate-y-1/2 rounded bg-cosci-toast-bg px-5 py-[0.82rem] ' +
  'text-[0.92rem] font-medium text-cosci-toast-fg';

export const COMPOSER_BASE_CLASSES =
  'reference-composer relative mt-4 min-h-[7.9rem] rounded-[2rem] border ' +
  'border-cosci-composer-border bg-cosci-composer-bg ' +
  'p-[1.25rem_1.5rem_0.8rem]';

export const COMPOSER_LABEL_CLASSES = 'relative block min-h-[3.6rem]';

export const COMPOSER_LABEL_TEXT_CLASSES =
  'absolute top-0 left-0 z-[1] flex h-6 items-center gap-[0.45rem] ' +
  'pointer-events-none text-base text-cosci-composer-label';

export const COMPOSER_LABEL_TEXT_HIDDEN_CLASSES = 'hidden';

export const COMPOSER_LABEL_ICON_CLASSES = 'text-[1.15rem]';

export const COMPOSER_TEXTAREA_CLASSES =
  'relative z-[2] block h-[3.6rem] max-h-[3.6rem] min-h-[3.6rem] w-full ' +
  'resize-none border-0 bg-transparent pt-0 font-[inherit] leading-6 ' +
  'text-cosci-composer-text outline-none';

export const COMPOSER_ACTIONS_CLASSES =
  'reference-composer-actions pointer-events-none absolute right-5 bottom-3 ' +
  'left-5 flex items-end justify-between gap-3';

export const COMPOSER_SOURCE_CONTROLS_CLASSES =
  'reference-composer-source-controls pointer-events-auto relative flex ' +
  'min-w-[4.6rem] items-center gap-[0.45rem]';

export const COMPOSER_FILE_INPUT_CLASSES =
  'reference-file-input absolute size-px overflow-hidden whitespace-nowrap ' +
  '[clip-path:inset(50%)] [clip:rect(0_0_0_0)]';

export const COMPOSER_SOURCE_BUTTON_CLASSES =
  'reference-composer-source-button pointer-events-auto inline-flex size-8 ' +
  'cursor-pointer items-center justify-center rounded-full border-0 ' +
  'bg-transparent p-0 text-cosci-source-button ' +
  'hover:bg-cosci-source-button-hover-bg ' +
  'hover:text-cosci-source-button-hover ' +
  'focus-visible:bg-cosci-source-button-hover-bg ' +
  'focus-visible:text-cosci-source-button-hover ' +
  'aria-expanded:bg-cosci-source-button-hover-bg ' +
  'aria-expanded:text-cosci-source-button-hover';

export const COMPOSER_SOURCE_ICON_CLASSES = 'text-xl';

export const COMPOSER_SUBMIT_BUTTON_CLASSES =
  'pointer-events-auto grid size-10 cursor-pointer place-items-center ' +
  'rounded-full border-0 bg-transparent p-0 text-cosci-composer-submit ' +
  'disabled:cursor-default disabled:text-cosci-composer-submit-disabled';

export const CONNECTORS_MENU_CLASSES =
  'reference-connectors-menu pointer-events-auto absolute bottom-[2.45rem] ' +
  'left-[2.35rem] z-10 w-56 overflow-hidden rounded-[0.9rem] border ' +
  'border-cosci-menu-border bg-cosci-menu-bg py-[0.45rem] ' +
  'text-cosci-menu-text';

export const CONNECTORS_MENU_HEADER_CLASSES =
  'reference-connectors-menu-row reference-connectors-menu-row--top grid ' +
  'min-h-[2.6rem] w-full grid-cols-[1fr] items-center border-0 border-b ' +
  'border-cosci-menu-divider bg-transparent px-[0.9rem] py-[0.45rem] ' +
  'font-medium text-inherit';

export const CONNECTORS_MENU_ROW_CLASSES =
  'reference-connectors-menu-row md-state grid min-h-[2.6rem] w-full ' +
  'cursor-pointer grid-cols-[1.35rem_1fr_auto] items-center gap-3 border-0 ' +
  'bg-transparent px-[0.9rem] py-[0.45rem] text-left font-[inherit] ' +
  'text-[0.9rem] text-inherit focus-visible:outline-none';

export const CONNECTOR_ICON_CLASSES =
  'reference-connector-icon text-[1.15rem] text-cosci-menu-icon';

export const CONNECTOR_TOGGLE_BASE_CLASSES =
  'reference-toggle relative h-[0.95rem] w-[1.6rem] rounded-full ' +
  'after:absolute after:top-[0.15rem] after:size-[0.65rem] ' +
  'after:rounded-full after:[content:""]';

export const CONNECTOR_TOGGLE_ON_CLASSES =
  'bg-cosci-toggle-on-track after:right-[0.18rem] ' +
  'after:bg-cosci-toggle-on-knob';

export const CONNECTOR_TOGGLE_OFF_CLASSES =
  'bg-cosci-toggle-off-track after:left-[0.18rem] ' +
  'after:bg-cosci-toggle-off-knob';

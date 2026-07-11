// Class strings for the home surface, which reproduces the Gemini reference
// 1:1. Any arbitrary rem values here are literal measurements copied from the
// reference and do NOT follow the app's 8px grid — that grid governs MD3 data
// surfaces only. See DESIGN.md > Layout & Spacing ("Reference-matched surfaces
// do not use the 8px grid").

// Outermost workspace shell (ChatWorkspace's root <div>/<main>).
export const HOME_WORKSPACE_CLASSES = 'reference-workspace';

export const HOME_WORKSPACE_MAIN_CLASSES = 'reference-workspace-main';

// Session-home stage layout: the centered greeting/suggestions/composer
// column (HOME_MAIN_CLASSES) plus its title, inside HOME_STAGE_CLASSES.
export const HOME_STAGE_CLASSES = 'reference-home-stage';

export const HOME_MAIN_CLASSES = 'reference-home-main';

export const HOME_TITLE_CLASSES = 'reference-home-title';

// Flask mark shown above the title on the phone home (relocated from the
// header); hidden on desktop, where the header lockup carries it.
export const HOME_LOGO_CLASSES = 'reference-home-logo';

// Desktop-only 1-2-3 onboarding timeline (see HomeStage's SESSION_STEPS):
// the ordered list, each step item (with center/end position variants for
// the connecting line), its numbered badge, heading, and body copy.
export const HOME_STEP_TIMELINE_CLASSES = 'reference-step-timeline';

export const HOME_STEP_ITEM_CLASSES = 'reference-step-item';

export const HOME_STEP_ITEM_CENTER_CLASSES = 'reference-step-item--center';

export const HOME_STEP_ITEM_END_CLASSES = 'reference-step-item--end';

export const HOME_STEP_BODY_CLASSES = 'reference-step-body';

export const HOME_STEP_NUMBER_CLASSES = 'reference-step-number';

export const HOME_STEP_HEADING_CLASSES = 'reference-step-heading';

// Suggestion prompt cards on the home stage (see HomeStage's SUGGESTIONS):
// the row of slots, each button (with a "previewed" state while hovered),
// its hover/focus preview bubble (positioned start/center/end per column),
// and the button's own truncated text.
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

// Leading glyph shown on the mobile suggestion list (hidden on the desktop
// card layout). Distinct per prompt, in the spirit of the reference home.
export const HOME_SUGGESTION_ICON_CLASSES = 'reference-suggestion-icon';

// Home-stage sizing overrides applied to the shared Composer when rendered
// with `large` (roomier padding/min-height than the in-conversation composer).
export const HOME_COMPOSER_CLASSES = 'reference-home-composer';

export const HOME_COMPOSER_TEXTAREA_CLASSES =
  'reference-home-composer-textarea';

// Recents panel (HomeRecentsPanel): the aside container, its list, the
// heading row, and the "show more/less" load-more control.
export const HOME_RECENTS_PANEL_CLASSES = 'reference-recents-panel';

export const HOME_RECENTS_LIST_CLASSES = 'reference-recents-list';

export const HOME_RECENTS_HEADING_ROW_CLASSES = 'reference-recents-heading';

export const HOME_LOAD_MORE_ITEM_CLASSES = 'reference-load-more-item';

export const HOME_LOAD_MORE_BUTTON_CLASSES = 'reference-load-more';

// Bottom-left snackbar (matching the reference): a message with an optional
// action button, anchored to the corner rather than floating mid-screen. z is
// above the nav rail (z-70) so the snackbar sits over it, and it is portaled to
// <body> so no ancestor stacking context can trap it.
export const HOME_TOAST_CLASSES =
  'reference-toast fixed bottom-4 left-4 z-[80] flex items-center gap-4 ' +
  'rounded-xl bg-cosci-toast-bg px-4 py-[0.7rem] text-[0.92rem] ' +
  'font-medium text-cosci-toast-fg';

export const HOME_TOAST_ACTION_CLASSES =
  'cursor-pointer border-0 bg-transparent p-0 font-[inherit] text-[0.92rem] ' +
  'font-medium text-cosci-toast-action focus-visible:outline-none focus-visible:underline';

// Composer shell: the bordered pill container itself.
export const COMPOSER_BASE_CLASSES =
  'reference-composer relative mt-4 min-h-[7.9rem] rounded-[2rem] border ' +
  'border-cosci-composer-border bg-cosci-composer-bg ' +
  'p-[1.25rem_1.5rem_0.8rem]';

// pb reserves room for the absolutely-positioned action row (send + source
// buttons) below the textarea, so the textarea can grow without its last lines
// sliding under the actions. It must exceed the action row's own footprint
// (~41px tall send button at bottom-3) with margin to spare — the textarea's
// min-height is shrunk by the matching amount below so the resting box keeps
// its height.
export const COMPOSER_LABEL_CLASSES =
  'relative block min-h-[3.6rem] pb-[3.5rem]';

export const COMPOSER_LABEL_TEXT_CLASSES =
  'absolute top-0 left-0 z-[1] flex h-6 items-center gap-[0.45rem] ' +
  'pointer-events-none text-base text-cosci-composer-label';

export const COMPOSER_LABEL_TEXT_HIDDEN_CLASSES = 'hidden';

export const COMPOSER_LABEL_ICON_CLASSES = 'text-[1.15rem]';

// Height is driven imperatively by the composer's auto-grow effect (min-height
// floor here, JS caps the max and toggles scrolling), so no fixed height. The
// floor is sized so that (empty textarea + the reserved action-row space below
// it, see COMPOSER_LABEL_CLASSES) lands at the composer's resting height rather
// than stacking on top of it and making the empty box too tall.
export const COMPOSER_TEXTAREA_CLASSES =
  'relative z-[2] block min-h-[2.35rem] w-full ' +
  'resize-none overflow-y-auto border-0 bg-transparent pt-0 font-[inherit] ' +
  'leading-6 text-cosci-composer-text outline-none';

// Bottom action row (source controls + submit), absolutely positioned over
// the textarea; pointer-events-none on the row itself so it doesn't block
// clicks into the textarea outside its children, which opt back in.
export const COMPOSER_ACTIONS_CLASSES =
  'reference-composer-actions pointer-events-none absolute right-5 bottom-3 ' +
  'left-5 flex items-end justify-between gap-3';

// File-upload and connectors buttons, plus the connectors dropdown anchor.
export const COMPOSER_SOURCE_CONTROLS_CLASSES =
  'reference-composer-source-controls pointer-events-auto relative flex ' +
  'min-w-[4.6rem] items-center gap-[0.45rem]';

export const COMPOSER_FILE_INPUT_CLASSES =
  'reference-file-input absolute size-px overflow-hidden whitespace-nowrap ' +
  '[clip-path:inset(50%)] [clip:rect(0_0_0_0)]';

// Shared round icon-button treatment: transparent by default with a circular
// hover/focus "state layer" that appears ONLY while the button is enabled, so
// every round icon button (composer source controls, submit) gets the same
// affordance and disabled buttons stay flat. Compose new round icon buttons
// from this rather than re-declaring the hover circle per button.
export const ICON_BUTTON_CLASSES =
  'pointer-events-auto inline-flex cursor-pointer items-center ' +
  'justify-center rounded-full border-0 bg-transparent p-0 transition-colors ' +
  'enabled:hover:bg-cosci-icon-button-hover-bg ' +
  'enabled:focus-visible:bg-cosci-icon-button-hover-bg ' +
  'focus-visible:outline-none disabled:cursor-default';

// Round source-control button (Files, Connectors), built on
// ICON_BUTTON_CLASSES; stays visibly "on" via aria-expanded while its menu
// is open.
export const COMPOSER_SOURCE_BUTTON_CLASSES =
  ICON_BUTTON_CLASSES +
  ' reference-composer-source-button size-8 text-cosci-source-button ' +
  'enabled:hover:text-cosci-source-button-hover ' +
  'enabled:focus-visible:text-cosci-source-button-hover ' +
  'aria-expanded:bg-cosci-icon-button-hover-bg ' +
  'aria-expanded:text-cosci-source-button-hover';

export const COMPOSER_SOURCE_ICON_CLASSES = 'text-xl';

// Round send button; dims via a distinct disabled-text color while the
// composer has no input or is otherwise disabled.
export const COMPOSER_SUBMIT_BUTTON_CLASSES =
  ICON_BUTTON_CLASSES +
  ' size-10 text-cosci-composer-submit ' +
  'disabled:text-cosci-composer-submit-disabled';

// Connectors dropdown: the floating menu panel, its header row, and each
// selectable connector row (see CONNECTOR_* below for the row's contents).
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

// Per-row connector icon and the on/off toggle switch (track + knob),
// selected between CONNECTOR_TOGGLE_ON_CLASSES / _OFF_CLASSES by state.
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

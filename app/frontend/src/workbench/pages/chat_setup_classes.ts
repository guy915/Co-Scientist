// Class strings for the chat/setup surface, which reproduces the Gemini
// reference 1:1. The arbitrary rem values here ([0.92rem], [1.18rem],
// [2.6rem], ...) are literal measurements copied from the reference and do
// NOT follow the app's 8px grid — that grid governs MD3 data surfaces only.
// Snapping these to the grid would break the pixel-match. See DESIGN.md >
// Layout & Spacing ("Reference-matched surfaces do not use the 8px grid").

// Shared recipe bases. The setup surface has two button families that recur;
// each variant composes from a base so the recipe lives in one place.

// Muted, transparent, round icon button. Variants add a size and an optional
// reference-* marker class. Exported so the field editor's remove-entry
// button (chat_timeline_run_spec_editor.tsx) can compose the same recipe.
export const MUTED_ICON_BUTTON =
  'grid cursor-pointer place-items-center rounded-full border-0 ' +
  'bg-transparent p-0 text-cosci-muted hover:bg-cosci-hover ' +
  'hover:text-cosci-fg focus-visible:bg-cosci-hover ' +
  'focus-visible:text-cosci-fg';

// Pill-shaped action button. Variants add colors, horizontal padding, and
// font weight.
const PILL_BUTTON = 'min-h-[2.6rem] cursor-pointer rounded-full border';

// Disabled state shared by the setup document's primary/secondary buttons.
const PILL_BUTTON_DISABLED =
  'disabled:cursor-default disabled:border-cosci-btn-disabled-border ' +
  'disabled:bg-cosci-btn-disabled-bg disabled:text-cosci-btn-disabled-fg';

// The timeline fills the column and scrolls under the overlaid composer.
// reference-chat-timeline (see home_surface.css) reserves the scrollbar gutter
// on both edges — so the centered column stays aligned with the composer's
// despite the scrollbar — and its bottom padding tracks the composer's measured
// height (--chat-composer-h) so the last item always scrolls fully clear of it.
export const CHAT_TIMELINE_CLASSES =
  'reference-chat-timeline flex-1 overflow-y-auto px-4 pt-5';

// The overlaid, non-scrolling composer wrapper (see the composer-height sync
// effect in chat_workspace.tsx for how CHAT_TIMELINE_CLASSES' bottom padding
// tracks this element's height).
export const CHAT_COMPOSER_CLASSES = 'reference-chat-composer px-4 pb-8';

// Shared centered column width used by both the timeline and the composer so
// their content stays aligned.
export const CHAT_COLUMN_CLASSES =
  'reference-chat-column mx-auto grid w-[min(100%,50.75rem)] gap-[1.15rem]';

// Bubble row containers: assistant messages left-align
// (CHAT_BUBBLE_ROW_CLASSES), user messages right-align and carry the
// `group/user` marker that the hover-revealed action row
// (MESSAGE_ACTIONS_END_CLASSES) keys off of.
// The assistant row's gap is the space between a reply and the action row
// under it, which sat close enough to read as part of the reply's last line.
export const CHAT_BUBBLE_ROW_CLASSES =
  'reference-bubble-row relative flex flex-col items-start justify-start ' +
  'gap-[0.7rem]';

export const CHAT_BUBBLE_USER_ROW_CLASSES =
  'reference-bubble-row user group/user relative flex flex-col items-end ' +
  'justify-end gap-[0.35rem]';

// User bubble chrome (bg, asymmetric corner radii). Its text styling and the
// expand/collapse affordance are the
// USER_BUBBLE_TEXT_*/USER_COLLAPSE_BUTTON_CLASSES group below.
export const USER_BUBBLE_CLASSES =
  'reference-user-bubble flex max-w-[31rem] items-start gap-4 ' +
  'rounded-tl-[26px] rounded-tr-[4px] rounded-br-[26px] rounded-bl-[26px] ' +
  'bg-cosci-user-bubble-bg py-3 pr-[0.9rem] pl-4 text-base ' +
  'leading-[1.45] text-cosci-fg';

const USER_BUBBLE_TEXT_BASE_CLASSES =
  'reference-user-bubble-text min-w-0 break-words';

export const USER_BUBBLE_TEXT_CLASSES =
  USER_BUBBLE_TEXT_BASE_CLASSES + ' whitespace-pre-wrap';

// A long request collapses to four lines and animates open/closed through an
// inline max-height that React drives. The collapsed state clips at the
// four-line max-height with `overflow: hidden`, so the last visible line ends
// on a whole word (letter-level `-webkit-line-clamp` would cut it mid-word);
// the expand chevron signals the hidden remainder. Whitespace is set per
// state, not on the base: the collapsed state collapses it so wrapping is
// compact, while the open state keeps pre-wrap so the sender's line breaks
// survive.
export const USER_BUBBLE_TEXT_COLLAPSIBLE_CLASSES =
  `${USER_BUBBLE_TEXT_BASE_CLASSES} overflow-hidden ` +
  'transition-[max-height] duration-300 ease-out motion-reduce:transition-none';

export const USER_BUBBLE_TEXT_CLAMP_CLASSES = 'block whitespace-normal';

export const USER_BUBBLE_TEXT_OPEN_CLASSES = 'block whitespace-pre-wrap';

// Mirrors MUTED_ICON_BUTTON but hovers with the on-bubble shade: this button
// lives inside the bubble, where the shared --cosci-hover equals the bubble bg
// and would be invisible.
export const USER_COLLAPSE_BUTTON_CLASSES =
  'reference-user-collapse size-8 shrink-0 grid cursor-pointer ' +
  'place-items-center rounded-full border-0 bg-transparent p-0 ' +
  'text-[1.25rem] ' +
  'text-cosci-muted hover:bg-cosci-user-bubble-hover hover:text-cosci-fg ' +
  'focus-visible:bg-cosci-user-bubble-hover focus-visible:text-cosci-fg';

// Assistant bubble: no background/border, just constrained width and body
// typography (contrast with the filled, rounded USER_BUBBLE_CLASSES).
export const MODEL_BUBBLE_CLASSES =
  'reference-model-bubble max-w-[50.75rem] text-base leading-[1.45] ' +
  'text-cosci-fg';

// Assistant bubble text. Deliberately *not* USER_BUBBLE_TEXT_CLASSES: that
// carries `whitespace-pre-wrap`, which is right for a plain-text span and
// wrong for rendered markdown. React-markdown emits a literal newline text
// node between adjacent block elements, so under pre-wrap every paragraph
// boundary painted a full extra line on top of its own margin and the reply
// read as double-spaced.
export const MODEL_BUBBLE_TEXT_CLASSES =
  'reference-model-bubble-text min-w-0 break-words';

// Message action row (retry/copy/download icons): the inline row shown below
// assistant bubbles (MESSAGE_ACTIONS_CLASSES) versus the row that floats over
// a user bubble's right edge on hover/focus (MESSAGE_ACTIONS_END_CLASSES),
// plus the shared icon-button and icon sizing used by both.
export const MESSAGE_ACTIONS_CLASSES =
  'reference-message-actions flex items-center gap-[0.2rem] px-[0.2rem]';

// Positioned against the bubble-hugging `w-fit` wrapper (see ChatBubble): its
// right edge sits 0.4rem left of the bubble's left edge, so the row tracks the
// bubble's real width for short and full-width prompts alike.
export const MESSAGE_ACTIONS_END_CLASSES =
  'reference-message-actions end pointer-events-none absolute top-1/2 ' +
  'z-[2] flex -translate-y-1/2 scale-[0.98] items-center gap-[0.2rem] ' +
  'border-0 bg-transparent p-[0.1rem] opacity-0 ' +
  '[right:calc(100%+0.4rem)] ' +
  'group-hover/user:pointer-events-auto group-hover/user:scale-100 ' +
  'group-hover/user:opacity-100 group-focus-within/user:pointer-events-auto ' +
  'group-focus-within/user:scale-100 group-focus-within/user:opacity-100';

export const MESSAGE_ACTION_BUTTON_CLASSES = `size-8 ${MUTED_ICON_BUTTON}`;

export const MESSAGE_ACTION_ICON_CLASSES = 'text-[1.12rem]';

// RunSpecCard attachment's fixed lead-in paragraph typography.
export const SETUP_PARAGRAPH_CLASSES = 'm-0 text-base leading-6';

// "Research plan" heading row (title + edit button) and its subheading,
// shown above the plan document card.
//
// No top margin of its own: the heading is one step in the attachment's own
// grid (MESSAGE_ATTACHMENT_CLASSES), and the extra 1.75rem on top of that
// gap opened a gulf between the Agent's reply and the plan it introduces --
// which read as two separate blocks rather than one message carrying a
// document.
export const PLAN_HEADING_CLASSES =
  'reference-plan-heading flex items-center gap-[0.45rem]';

export const PLAN_TITLE_CLASSES =
  'm-0 text-[2rem] leading-[1.2] font-normal tracking-normal text-cosci-fg ' +
  'max-[720px]:text-[clamp(1.5rem,6.8vw,2rem)]';

export const PLAN_EDIT_BUTTON_CLASSES =
  'reference-plan-edit size-[2.1rem] ' + MUTED_ICON_BUTTON;

export const PLAN_EDIT_ICON_CLASSES = 'text-[1.55rem] text-current';

export const PLAN_SUBHEADING_CLASSES =
  'reference-plan-subheading -mt-[0.35rem] m-0 text-cosci-muted';

// The tinted "document" card that contains the plan title, the spec
// definition list, the focus/tier option groups, and the action buttons.
export const SETUP_DOCUMENT_CLASSES =
  'reference-setup-document grid gap-[1.15rem] rounded-2xl ' +
  'bg-cosci-setup-doc-bg p-[1.5rem_1.45rem]';

export const SETUP_DOCUMENT_TITLE_CLASSES =
  'm-0 text-[1.45rem] leading-[1.25] font-semibold';

// Definition-list rendering of the run spec (Goal/Requirements/Attributes/
// Criteria): the grid, each row's term/detail pair, and bulleted-list rows.
export const SPEC_GRID_CLASSES = 'reference-setup-grid m-0 grid gap-[1.55rem]';

export const SPEC_ROW_CLASSES = 'reference-spec-row block text-base';

export const SPEC_TERM_CLASSES =
  'mb-[0.85rem] text-[1.18rem] font-bold text-cosci-fg';

export const SPEC_DETAIL_CLASSES = 'm-0 leading-[1.45] text-cosci-fg';

export const SPEC_LIST_CLASSES =
  'reference-spec-list m-0 grid list-disc gap-[0.8rem] pl-[1.35rem]';

// Radio-card option groups (Focus/Tier selectors in RunOptionGroup): the
// fieldset/legend, the responsive card grid, each selectable card (with a
// selected-marker variant), the visually-hidden native radio input, and the
// card's label/description text.
export const OPTION_GROUP_CLASSES =
  'reference-option-group m-0 grid min-w-0 gap-[0.9rem] border-0 p-0';

export const OPTION_GROUP_LEGEND_CLASSES =
  'text-[1.18rem] font-bold text-cosci-fg';

export const OPTION_GRID_CLASSES =
  'grid grid-cols-2 gap-[0.85rem] max-[720px]:grid-cols-1';

export const OPTION_CARD_BASE_CLASSES =
  'reference-option-card relative grid min-h-[4.75rem] ' +
  'grid-cols-[1.6rem_minmax(0,1fr)] ' +
  'content-start gap-x-[0.8rem] rounded-[0.65rem] border border-transparent ' +
  'bg-cosci-option-bg px-[0.95rem] py-[0.85rem] text-cosci-fg ' +
  'hover:bg-cosci-option-hover-bg ' +
  'has-[:focus-visible]:border-cosci-option-hover-border ' +
  'has-[:focus-visible]:bg-cosci-option-hover-bg';

export const OPTION_INPUT_CLASSES = 'absolute pointer-events-none opacity-0';

export const OPTION_MARKER_CLASSES =
  'mt-[0.08rem] size-[1.28rem] rounded-full border-2 ' +
  'border-cosci-option-marker';

export const OPTION_MARKER_SELECTED_CLASSES =
  'border-cosci-option-marker-on ' +
  'bg-[radial-gradient(circle,var(--cosci-option-marker-on)_0_42%,transparent_44%)]';

export const OPTION_LABEL_CLASSES = 'min-w-0 text-base leading-[1.2] font-bold';

export const OPTION_DESCRIPTION_CLASSES =
  'col-start-2 text-[0.92rem] leading-[1.3] text-cosci-muted';

// The question chooser that grows out of the top of the composer while an
// Agent turn is waiting on a choice (chat_questions_panel.tsx). It renders
// INSIDE the composer's own form, so it inherits the composer's shell,
// border and shadow and reads as the input box expanding upward rather than
// as a card floating above it -- hence a bottom rule instead of a border,
// and no background of its own.
export const QUESTIONS_PANEL_CLASSES =
  'reference-questions-panel mb-[0.9rem] grid gap-[0.85rem] ' +
  'border-b border-cosci-composer-border pb-[0.9rem]';

// The chooser's own title row: what is being asked about, then the minimize
// and dismiss controls.
export const QUESTIONS_HEAD_CLASSES =
  'flex min-w-0 items-center justify-between gap-[0.6rem]';

export const QUESTIONS_HEAD_LABEL_CLASSES =
  'min-w-0 truncate text-[0.82rem] font-medium tracking-[0.04em] uppercase ' +
  'text-cosci-muted';

export const QUESTIONS_HEAD_ACTIONS_CLASSES =
  'flex shrink-0 items-center gap-[0.15rem]';

export const QUESTIONS_ICON_BUTTON_CLASSES = `${MUTED_ICON_BUTTON} size-8`;

export const QUESTIONS_ICON_CLASSES = 'size-[1.1rem]';

// One question inside the chooser: its prompt, then its answers.
export const QUESTION_GROUP_CLASSES =
  'm-0 grid min-w-0 gap-[0.6rem] border-0 p-0';

export const QUESTION_PROMPT_CLASSES =
  'text-base leading-[1.35] font-medium text-cosci-fg';

// The scientist's own wording, revealed by choosing "Something else".
export const QUESTION_OTHER_INPUT_CLASSES =
  'w-full rounded-[0.65rem] border border-cosci-composer-border ' +
  'bg-transparent px-[0.85rem] py-[0.6rem] text-base text-cosci-fg ' +
  'outline-none placeholder:text-cosci-composer-label ' +
  'focus:border-cosci-option-hover-border';

// The multi-select marker. Deliberately NOT composed from
// OPTION_MARKER_CLASSES with a radius override: both are utilities for the
// same property, so which one wins is decided by their order in the
// generated stylesheet rather than in the class attribute, and `rounded-full`
// won -- every checkbox rendered as a radio. A checkbox and a radio must be
// told apart at a glance, since the difference is whether one answer or
// several can hold.
export const QUESTION_CHECKBOX_MARKER_CLASSES =
  'mt-[0.08rem] grid size-[1.28rem] place-items-center rounded-[0.35rem] ' +
  'border-2 border-cosci-option-marker';

export const QUESTION_CHECKBOX_MARKER_SELECTED_CLASSES =
  'border-cosci-option-marker-on bg-cosci-option-marker-on';

// The tick inside a chosen checkbox, drawn on the filled marker.
export const QUESTION_CHECKBOX_TICK_CLASSES =
  'size-[0.95rem] text-cosci-composer-bg';

// The row carrying the chooser's send control, present whenever a click
// alone cannot be taken as the whole answer.
export const QUESTIONS_SEND_ROW_CLASSES = 'flex justify-end';

// The chooser's own answer list: one column, each answer a full-width row.
// A dedicated constant rather than reusing OPTION_GRID_CLASSES -- that one
// is the Focus/Run type picker's 2-column card grid, and the two must be
// free to diverge.
export const QUESTION_OPTION_GRID_CLASSES = 'grid grid-cols-1 gap-[0.6rem]';

// One answer row: the marker on the left, its label and description running
// horizontally to the right rather than stacked, since a full-width row has
// the room. `items-center` (not OPTION_CARD_BASE_CLASSES's `content-start`)
// keeps a description-less row from looking top-heavy.
export const QUESTION_OPTION_ROW_CLASSES =
  'relative grid min-h-[3.2rem] grid-cols-[1.6rem_minmax(0,1fr)] ' +
  'items-center gap-x-[0.8rem] rounded-[0.65rem] border border-transparent ' +
  'bg-cosci-option-bg px-[0.95rem] py-[0.7rem] text-cosci-fg ' +
  'hover:bg-cosci-option-hover-bg ' +
  'has-[:focus-visible]:border-cosci-option-hover-border ' +
  'has-[:focus-visible]:bg-cosci-option-hover-bg';

// The label/description pair inside one answer row, wrapping as a horizontal
// run of text instead of OPTION_DESCRIPTION_CLASSES's grid-row stack.
export const QUESTION_OPTION_TEXT_CLASSES =
  'flex min-w-0 flex-wrap items-baseline gap-x-[0.5rem]';

// The muted description half of that horizontal pair -- OPTION_DESCRIPTION_
// CLASSES without its `col-start-2`, which only means something in a grid.
export const QUESTION_OPTION_DESCRIPTION_CLASSES =
  'min-w-0 text-[0.92rem] leading-[1.3] text-cosci-muted';

// Cancel/Start research button row at the bottom of the plan document card.
export const SETUP_ACTIONS_CLASSES =
  'reference-setup-actions flex justify-end gap-[0.7rem] pt-[0.3rem]';

export const SETUP_SECONDARY_BUTTON_CLASSES =
  `${PILL_BUTTON} border-cosci-btn-secondary-border bg-transparent ` +
  'px-[1.45rem] font-medium text-cosci-btn-secondary-fg ' +
  'hover:bg-cosci-btn-secondary-hover-bg ' +
  `focus-visible:bg-cosci-btn-secondary-hover-bg ${PILL_BUTTON_DISABLED}`;

export const SETUP_PRIMARY_BUTTON_CLASSES =
  `${PILL_BUTTON} border-cosci-btn-primary-bg bg-cosci-btn-primary-bg ` +
  'px-[1.45rem] font-medium text-cosci-btn-primary-fg ' +
  'hover:bg-cosci-btn-primary-hover ' +
  `focus-visible:bg-cosci-btn-primary-hover ${PILL_BUTTON_DISABLED}`;

// The clickable colored session card (title/meta + "Open" affordance) linking
// to the run's detail page.
export const STARTED_SESSION_CARD_CLASSES =
  'reference-started-session-card grid min-h-[5.3rem] cursor-pointer ' +
  'grid-cols-[minmax(0,1fr)_auto] items-center gap-[1.2rem] rounded-2xl ' +
  'border-0 p-[1rem_1rem_1rem_1.35rem] text-left text-white';

export const STARTED_SESSION_TITLE_CLASSES =
  'block min-w-0 text-[1.18rem] leading-[1.25]';

export const STARTED_SESSION_META_CLASSES =
  'mt-[0.3rem] block text-[0.9rem] text-white/80';

export const STARTED_OPEN_CLASSES =
  'reference-started-open min-w-[5.4rem] rounded-full border ' +
  'border-white/75 px-[1.25rem] py-[0.65rem] text-center font-semibold ' +
  'text-white/90 hover:bg-white/12 focus-visible:bg-white/12';

// "What would you like to do next?" row: its copy label and the pill buttons
// (view details / start a new topic) that follow it.
export const STARTED_NEXT_CLASSES =
  'reference-started-next flex flex-wrap items-center gap-[0.55rem]';

export const STARTED_NEXT_COPY_CLASSES =
  'basis-full m-0 mb-[0.1rem] text-[0.95rem] font-semibold text-cosci-muted';

export const STARTED_NEXT_BUTTON_CLASSES =
  `${PILL_BUTTON} border-cosci-btn-outline-border bg-transparent ` +
  'px-[1.2rem] font-semibold text-cosci-btn-outline-fg ' +
  'hover:bg-cosci-btn-outline-hover-bg ' +
  'focus-visible:bg-cosci-btn-outline-hover-bg';

// In-place field editor (chat_timeline_run_spec_editor.tsx): the form's
// field/list/error chrome and its Save/Cancel row (reuses
// SETUP_ACTIONS_CLASSES and the two SETUP_*_BUTTON_CLASSES above, matching
// the Cancel/Start row's own style). The form is opened from the card's
// heading pencil (PLAN_EDIT_BUTTON_CLASSES), not from inside the box.

export const SPEC_EDIT_FORM_CLASSES =
  'reference-spec-edit-form grid gap-[1.15rem]';

export const SPEC_EDIT_FIELD_CLASSES = 'grid gap-[0.5rem]';

export const SPEC_EDIT_LABEL_CLASSES = 'text-[1.18rem] font-bold text-cosci-fg';

// Shared bordered-control look for the goal textarea, title input, and each
// list entry's text input.
const SPEC_EDIT_CONTROL_BASE =
  'w-full rounded-[0.65rem] border border-cosci-composer-border ' +
  'bg-cosci-composer-bg px-[0.85rem] py-[0.6rem] text-base ' +
  'text-cosci-composer-text outline-none focus-visible:border-cosci-fg';

export const SPEC_EDIT_TEXTAREA_CLASSES =
  SPEC_EDIT_CONTROL_BASE + ' min-h-[6rem] resize-y leading-[1.45]';

export const SPEC_EDIT_INPUT_CLASSES = SPEC_EDIT_CONTROL_BASE;

export const SPEC_EDIT_FIELDSET_CLASSES = 'm-0 grid gap-[0.6rem] border-0 p-0';

export const SPEC_EDIT_LEGEND_CLASSES = SPEC_EDIT_LABEL_CLASSES;

export const SPEC_EDIT_LIST_ROW_CLASSES = 'flex items-center gap-[0.5rem]';

export const SPEC_EDIT_REMOVE_BUTTON_CLASSES =
  'size-[2.1rem] shrink-0 ' + MUTED_ICON_BUTTON;

export const SPEC_EDIT_REMOVE_ICON_CLASSES = 'text-[1.15rem]';

export const SPEC_EDIT_ADD_BUTTON_CLASSES =
  'reference-spec-edit-add flex w-fit cursor-pointer items-center ' +
  'gap-[0.3rem] rounded-full border-0 bg-transparent px-[0.2rem] ' +
  'py-[0.3rem] text-[0.9rem] font-medium text-cosci-muted ' +
  'hover:text-cosci-fg focus-visible:text-cosci-fg';

export const SPEC_EDIT_ADD_ICON_CLASSES = 'text-[1.05rem]';

export const SPEC_EDIT_ERROR_CLASSES = 'm-0 text-[0.9rem]';

// Wrapper for an inline attachment an assistant message carries (the
// research-plan document, the started-session block): one shared class so
// every attachment sits in the message's own flow rather than each
// inventing its own spacing. The top margin is the same distance a plain
// reply keeps from its own action row (CHAT_BUBBLE_ROW_CLASSES' gap), so an
// attachment reads as the next thing in the message rather than a
// differently-spaced card bolted on after it.
export const MESSAGE_ATTACHMENT_CLASSES =
  'reference-message-attachment mt-[0.7rem] grid gap-[1.15rem]';

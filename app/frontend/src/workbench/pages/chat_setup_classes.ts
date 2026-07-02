export const CHAT_TIMELINE_CLASSES = 'flex-1 overflow-y-auto px-4 pt-5 pb-8';

export const CHAT_COMPOSER_CLASSES = 'border-t-0 bg-transparent px-4 pb-8';

export const CHAT_COLUMN_CLASSES =
  'reference-chat-column mx-auto grid w-[min(100%,50.75rem)] gap-[1.15rem]';

export const CHAT_BUBBLE_ROW_CLASSES =
  'reference-bubble-row relative flex flex-col items-start justify-start ' +
  'gap-[0.35rem]';

export const CHAT_BUBBLE_USER_ROW_CLASSES =
  'reference-bubble-row user group/user relative flex flex-col items-end ' +
  'justify-end gap-[0.35rem]';

export const USER_BUBBLE_CLASSES =
  'reference-user-bubble flex max-w-[31rem] items-start gap-4 rounded-2xl ' +
  'bg-[var(--cosci-user-bubble-bg)] py-3 pr-[0.9rem] pl-4 text-base ' +
  'leading-[1.45] text-cosci-fg';

export const USER_BUBBLE_TEXT_CLASSES =
  'reference-user-bubble-text min-w-0 whitespace-pre-wrap break-words';

export const USER_BUBBLE_TEXT_COLLAPSED_CLASSES = `${USER_BUBBLE_TEXT_CLASSES} line-clamp-3`;

export const USER_COLLAPSE_BUTTON_CLASSES =
  'reference-user-collapse ml-1 grid size-6 shrink-0 cursor-pointer ' +
  'place-items-center rounded-full border-0 bg-transparent p-0 ' +
  'text-cosci-muted hover:bg-cosci-hover hover:text-cosci-fg ' +
  'focus-visible:bg-cosci-hover focus-visible:text-cosci-fg';

export const MODEL_BUBBLE_CLASSES =
  'reference-model-bubble max-w-[50.75rem] text-base leading-[1.45] ' +
  'text-cosci-fg';

export const MESSAGE_ACTIONS_CLASSES =
  'reference-message-actions flex items-center gap-[0.2rem] px-[0.2rem]';

export const MESSAGE_ACTIONS_END_CLASSES =
  'reference-message-actions end pointer-events-none absolute top-1/2 ' +
  'z-[2] flex -translate-y-1/2 scale-[0.98] items-center gap-[0.2rem] ' +
  'rounded-full border border-cosci-border bg-[var(--cosci-surface-raised)] ' +
  'p-[0.1rem] opacity-0 [right:calc(min(31rem,72vw)+0.4rem)] ' +
  'group-hover/user:pointer-events-auto group-hover/user:scale-100 ' +
  'group-hover/user:opacity-100 group-focus-within/user:pointer-events-auto ' +
  'group-focus-within/user:scale-100 group-focus-within/user:opacity-100';

export const MESSAGE_ACTION_BUTTON_CLASSES =
  'grid size-8 cursor-pointer place-items-center rounded-full border-0 ' +
  'bg-transparent p-0 text-cosci-muted hover:bg-cosci-hover ' +
  'hover:text-cosci-fg focus-visible:bg-cosci-hover ' +
  'focus-visible:text-cosci-fg';

export const MESSAGE_ACTION_ICON_CLASSES = 'text-[1.12rem]';

export const SETUP_MESSAGE_CLASSES =
  'reference-setup-message grid gap-[1.15rem] text-cosci-fg';

export const SETUP_PARAGRAPH_CLASSES = 'm-0 text-base leading-6';

export const PLAN_HEADING_CLASSES =
  'reference-plan-heading mt-7 flex items-center gap-[0.45rem]';

export const PLAN_TITLE_CLASSES =
  'm-0 text-[2rem] leading-[1.2] font-normal tracking-normal text-cosci-fg';

export const PLAN_EDIT_BUTTON_CLASSES =
  'reference-plan-edit grid size-[2.1rem] cursor-pointer place-items-center ' +
  'rounded-full border-0 bg-transparent p-0 text-cosci-muted ' +
  'hover:bg-cosci-hover hover:text-cosci-fg focus-visible:bg-cosci-hover ' +
  'focus-visible:text-cosci-fg';

export const PLAN_EDIT_ICON_CLASSES = 'text-[1.55rem] text-current';

export const PLAN_SUBHEADING_CLASSES =
  'reference-plan-subheading -mt-[0.35rem] m-0 text-cosci-muted';

export const SETUP_DOCUMENT_CLASSES =
  'reference-setup-document grid gap-[1.15rem] rounded-2xl ' +
  'bg-[var(--cosci-setup-doc-bg)] p-[1.5rem_1.45rem]';

export const SETUP_DOCUMENT_TITLE_CLASSES =
  'm-0 text-[1.45rem] leading-[1.25] font-semibold';

export const SPEC_GRID_CLASSES = 'google-setup-grid m-0 grid gap-[1.55rem]';

export const SPEC_ROW_CLASSES = 'google-spec-row block text-base';

export const SPEC_TERM_CLASSES =
  'mb-[0.85rem] text-[1.18rem] font-bold text-cosci-fg';

export const SPEC_DETAIL_CLASSES = 'm-0 leading-[1.45] text-cosci-fg';

export const SPEC_LIST_CLASSES =
  'google-spec-list m-0 grid list-disc gap-[0.8rem] pl-[1.35rem]';

export const OPTION_GROUP_CLASSES =
  'reference-option-group m-0 grid min-w-0 gap-[0.9rem] border-0 p-0';

export const OPTION_GROUP_LEGEND_CLASSES =
  'text-[1.18rem] font-bold text-cosci-fg';

export const OPTION_GRID_CLASSES = 'grid grid-cols-2 gap-[0.85rem]';

export const OPTION_CARD_BASE_CLASSES =
  'reference-option-card relative grid min-h-[4.75rem] grid-cols-[1.6rem_minmax(0,1fr)] ' +
  'content-start gap-x-[0.8rem] rounded-[0.65rem] border border-transparent ' +
  'bg-[var(--cosci-option-bg)] px-[0.95rem] py-[0.85rem] text-cosci-fg ' +
  'hover:border-[var(--cosci-option-hover-border)] ' +
  'hover:bg-[var(--cosci-option-hover-bg)] ' +
  'focus-within:border-[var(--cosci-option-hover-border)] ' +
  'focus-within:bg-[var(--cosci-option-hover-bg)]';

export const OPTION_CARD_SELECTED_CLASSES =
  'selected bg-[var(--cosci-option-selected-bg)]';

export const OPTION_INPUT_CLASSES = 'absolute pointer-events-none opacity-0';

export const OPTION_MARKER_CLASSES =
  'mt-[0.08rem] size-[1.28rem] rounded-full border-2 ' +
  'border-[var(--cosci-option-marker)]';

export const OPTION_MARKER_SELECTED_CLASSES =
  'selected border-[var(--cosci-option-marker-on)] ' +
  'bg-[var(--cosci-option-marker-on)]';

export const OPTION_LABEL_CLASSES = 'min-w-0 text-base leading-[1.2] font-bold';

export const OPTION_DESCRIPTION_CLASSES =
  'col-start-2 text-[0.92rem] leading-[1.3] text-cosci-muted';

export const SETUP_ACTIONS_CLASSES =
  'reference-setup-actions flex justify-end gap-[0.7rem] pt-[0.3rem]';

export const SETUP_SECONDARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border ' +
  'border-[var(--cosci-btn-secondary-border)] bg-transparent px-[1.45rem] ' +
  'font-medium text-[var(--cosci-btn-secondary-fg)] ' +
  'hover:bg-[var(--cosci-btn-secondary-hover-bg)] ' +
  'focus-visible:bg-[var(--cosci-btn-secondary-hover-bg)] ' +
  'disabled:cursor-default disabled:border-[var(--cosci-btn-disabled-border)] ' +
  'disabled:bg-[var(--cosci-btn-disabled-bg)] ' +
  'disabled:text-[var(--cosci-btn-disabled-fg)]';

export const SETUP_PRIMARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border ' +
  'border-[var(--cosci-btn-primary-bg)] bg-[var(--cosci-btn-primary-bg)] ' +
  'px-[1.45rem] font-medium text-[var(--cosci-btn-primary-fg)] ' +
  'hover:bg-[var(--cosci-btn-primary-hover)] ' +
  'focus-visible:bg-[var(--cosci-btn-primary-hover)] disabled:cursor-default ' +
  'disabled:border-[var(--cosci-btn-disabled-border)] ' +
  'disabled:bg-[var(--cosci-btn-disabled-bg)] ' +
  'disabled:text-[var(--cosci-btn-disabled-fg)]';

export const STARTED_MESSAGE_CLASSES =
  'reference-started-message grid gap-[1.15rem] text-cosci-fg';

export const STARTED_COPY_CLASSES = 'reference-started-copy grid gap-[0.1rem]';

export const STARTED_COPY_PARAGRAPH_CLASSES = 'm-0 text-base leading-[1.45]';

export const STARTED_SESSION_CARD_CLASSES =
  'reference-started-session-card grid min-h-[5.3rem] cursor-pointer ' +
  'grid-cols-[minmax(0,1fr)_auto] items-center gap-[1.2rem] rounded-2xl ' +
  'border-0 p-[1rem_1rem_1rem_1.35rem] text-left text-white';

export const STARTED_SESSION_TITLE_CLASSES =
  'line-clamp-1 text-[1.18rem] leading-[1.25]';

export const STARTED_SESSION_META_CLASSES =
  'mt-[0.3rem] block text-[0.9rem] text-white/80';

export const STARTED_OPEN_CLASSES =
  'reference-started-open min-w-[5.4rem] rounded-full border ' +
  'border-white/75 px-[1.25rem] py-[0.65rem] text-center font-semibold ' +
  'text-white/90 hover:bg-white/12 focus-visible:bg-white/12';

export const STARTED_NEXT_CLASSES =
  'reference-started-next flex flex-wrap items-center gap-[0.55rem]';

export const STARTED_NEXT_COPY_CLASSES =
  'basis-full m-0 mb-[0.1rem] text-[0.95rem] font-semibold text-cosci-muted';

export const STARTED_NEXT_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border ' +
  'border-[var(--cosci-btn-outline-border)] bg-transparent px-[1.2rem] ' +
  'font-semibold text-[var(--cosci-btn-outline-fg)] ' +
  'hover:bg-[var(--cosci-btn-outline-hover-bg)] ' +
  'focus-visible:bg-[var(--cosci-btn-outline-hover-bg)]';

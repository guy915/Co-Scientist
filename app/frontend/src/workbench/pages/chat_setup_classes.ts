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
  'bg-[#e9eefb] py-3 pr-[0.9rem] pl-4 text-base leading-[1.45] ' +
  'text-[#202124] dark:bg-[#303134] dark:text-[var(--cosci-text)]';

export const USER_BUBBLE_TEXT_CLASSES =
  'reference-user-bubble-text min-w-0 whitespace-pre-wrap break-words';

export const USER_BUBBLE_TEXT_COLLAPSED_CLASSES = `${USER_BUBBLE_TEXT_CLASSES} line-clamp-3`;

export const USER_COLLAPSE_BUTTON_CLASSES =
  'reference-user-collapse ml-1 grid size-6 shrink-0 cursor-pointer ' +
  'place-items-center rounded-full border-0 bg-transparent p-0 text-[#5f6368] ' +
  'hover:bg-[#dce6f7] focus-visible:bg-[#dce6f7] ' +
  'dark:text-[#bdc1c6] dark:hover:bg-[#3c4043] ' +
  'dark:focus-visible:bg-[#3c4043]';

export const MODEL_BUBBLE_CLASSES =
  'reference-model-bubble max-w-[50.75rem] text-base leading-[1.45] ' +
  'text-[#202124] dark:text-[var(--cosci-text)]';

export const MESSAGE_ACTIONS_CLASSES =
  'reference-message-actions flex items-center gap-[0.2rem] px-[0.2rem]';

export const MESSAGE_ACTIONS_END_CLASSES =
  'reference-message-actions end pointer-events-none absolute top-1/2 ' +
  'z-[2] flex -translate-y-1/2 scale-[0.98] items-center gap-[0.2rem] ' +
  'rounded-full border border-[#dadce0] bg-white p-[0.1rem] opacity-0 ' +
  'shadow-[0_1px_3px_rgba(60,64,67,0.18)] ' +
  '[right:calc(min(31rem,72vw)+0.4rem)] ' +
  'group-hover/user:pointer-events-auto group-hover/user:scale-100 ' +
  'group-hover/user:opacity-100 group-focus-within/user:pointer-events-auto ' +
  'group-focus-within/user:scale-100 group-focus-within/user:opacity-100 ' +
  'dark:border-[#3c4043] dark:bg-[#202124] ' +
  'dark:shadow-[0_1px_4px_rgba(0,0,0,0.34)]';

export const MESSAGE_ACTION_BUTTON_CLASSES =
  'grid size-8 cursor-pointer place-items-center rounded-full border-0 ' +
  'bg-transparent p-0 text-[#5f6368] hover:bg-[#f1f3f4] ' +
  'hover:text-[#202124] focus-visible:bg-[#f1f3f4] ' +
  'focus-visible:text-[#202124] dark:text-[#bdc1c6] ' +
  'dark:hover:bg-[#303134] dark:hover:text-[#e8eaed] ' +
  'dark:focus-visible:bg-[#303134] dark:focus-visible:text-[#e8eaed]';

export const MESSAGE_ACTION_ICON_CLASSES = 'text-[1.12rem]';

export const SETUP_MESSAGE_CLASSES =
  'reference-setup-message grid gap-[1.15rem] text-[#202124] ' +
  'dark:text-[var(--cosci-text)]';

export const SETUP_PARAGRAPH_CLASSES = 'm-0 text-base leading-6';

export const PLAN_HEADING_CLASSES =
  'reference-plan-heading mt-7 flex items-center gap-[0.45rem]';

export const PLAN_TITLE_CLASSES =
  'm-0 text-[2rem] leading-[1.2] font-normal tracking-normal ' +
  'text-[#202124] dark:text-[var(--cosci-text)]';

export const PLAN_EDIT_BUTTON_CLASSES =
  'reference-plan-edit grid size-[2.1rem] cursor-pointer place-items-center ' +
  'rounded-full border-0 bg-transparent p-0 text-[#5f6368] ' +
  'hover:bg-[#eef4f3] hover:text-[#1a6b6b] focus-visible:bg-[#eef4f3] ' +
  'focus-visible:text-[#1a6b6b] dark:text-[#bdc1c6] ' +
  'dark:hover:bg-[#2a2d2f] dark:hover:text-[#8fd8c7] ' +
  'dark:focus-visible:bg-[#2a2d2f] dark:focus-visible:text-[#8fd8c7]';

export const PLAN_EDIT_ICON_CLASSES = 'text-[1.55rem] text-current';

export const PLAN_SUBHEADING_CLASSES =
  'reference-plan-subheading -mt-[0.35rem] m-0 text-[#3c4043] ' +
  'dark:text-[var(--cosci-text)]';

export const SETUP_DOCUMENT_CLASSES =
  'reference-setup-document grid gap-[1.15rem] rounded-2xl ' +
  'bg-[var(--idea-ref-card-bg)] p-[1.5rem_1.45rem] dark:bg-[#25272d]';

export const SETUP_DOCUMENT_TITLE_CLASSES =
  'm-0 text-[1.45rem] leading-[1.25] font-semibold';

export const SPEC_GRID_CLASSES = 'google-setup-grid m-0 grid gap-[1.55rem]';

export const SPEC_ROW_CLASSES = 'google-spec-row block text-base';

export const SPEC_TERM_CLASSES =
  'mb-[0.85rem] text-[1.18rem] font-bold text-[#202124] ' +
  'dark:text-[var(--cosci-text)]';

export const SPEC_DETAIL_CLASSES =
  'm-0 leading-[1.45] text-[#202124] dark:text-[var(--cosci-text)]';

export const SPEC_LIST_CLASSES =
  'google-spec-list m-0 grid list-disc gap-[0.8rem] pl-[1.35rem]';

export const OPTION_GROUP_CLASSES =
  'reference-option-group m-0 grid min-w-0 gap-[0.9rem] border-0 p-0';

export const OPTION_GROUP_LEGEND_CLASSES =
  'text-[1.18rem] font-bold text-[#202124] dark:text-[var(--cosci-text)]';

export const OPTION_GRID_CLASSES = 'grid grid-cols-2 gap-[0.85rem]';

export const OPTION_CARD_BASE_CLASSES =
  'reference-option-card relative grid min-h-[4.75rem] grid-cols-[1.6rem_minmax(0,1fr)] ' +
  'content-start gap-x-[0.8rem] rounded-[0.65rem] border border-transparent ' +
  'bg-white px-[0.95rem] py-[0.85rem] text-[#202124] ' +
  'hover:border-[#d4dbe6] hover:bg-[#e8eef6] focus-within:border-[#d4dbe6] ' +
  'focus-within:bg-[#e8eef6] dark:bg-[#202427] dark:text-[var(--cosci-text)] ' +
  'dark:hover:border-[#3c4043] dark:hover:bg-[#252a2d] ' +
  'dark:focus-within:border-[#3c4043] dark:focus-within:bg-[#252a2d]';

export const OPTION_CARD_SELECTED_CLASSES =
  'selected bg-[#e5eefc] dark:bg-[#1f2224]';

export const OPTION_INPUT_CLASSES = 'absolute pointer-events-none opacity-0';

export const OPTION_MARKER_CLASSES =
  'mt-[0.08rem] size-[1.28rem] rounded-full border-2 border-[#5f6368] ' +
  'dark:border-[var(--cosci-blue)]';

export const OPTION_MARKER_SELECTED_CLASSES =
  'border-[#8ab4f8] bg-[#8ab4f8] shadow-[inset_0_0_0_0.25rem_#e5eefc] ' +
  'dark:border-[var(--cosci-blue)] dark:bg-[var(--cosci-blue)] ' +
  'dark:shadow-[inset_0_0_0_0.25rem_#1f2224]';

export const OPTION_LABEL_CLASSES = 'min-w-0 text-base leading-[1.2] font-bold';

export const OPTION_DESCRIPTION_CLASSES =
  'col-start-2 text-[0.92rem] leading-[1.3] text-[#5f6368] ' +
  'dark:text-[#bdc1c6]';

export const SETUP_ACTIONS_CLASSES =
  'reference-setup-actions flex justify-end gap-[0.7rem] pt-[0.3rem]';

export const SETUP_SECONDARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-[#9aa0a6] ' +
  'bg-transparent px-[1.45rem] font-medium text-[#3c4043] disabled:cursor-default ' +
  'disabled:border-[#dadce0] disabled:bg-[#f1f3f4] disabled:text-[#9aa0a6] ' +
  'dark:border-[var(--cosci-border)] dark:text-[var(--cosci-text)] ' +
  'dark:disabled:border-[#3c4043] dark:disabled:bg-[#202124] ' +
  'dark:disabled:text-[#5f6368]';

export const SETUP_PRIMARY_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-[var(--idea-ref-blue)] ' +
  'bg-[var(--idea-ref-blue)] px-[1.45rem] font-medium text-white ' +
  'hover:bg-[#0842a0] focus-visible:bg-[#0842a0] disabled:cursor-default ' +
  'disabled:border-[#dadce0] disabled:bg-[#f1f3f4] disabled:text-[#9aa0a6] ' +
  'dark:border-[#1d3354] dark:bg-[#1d3354] dark:text-[var(--cosci-blue)] ' +
  'dark:hover:bg-[rgba(127,215,191,0.14)] ' +
  'dark:focus-visible:bg-[rgba(127,215,191,0.14)] ' +
  'dark:disabled:border-[#3c4043] dark:disabled:bg-[#202124] ' +
  'dark:disabled:text-[#5f6368]';

export const STARTED_MESSAGE_CLASSES =
  'reference-started-message grid gap-[1.15rem] text-[#202124] ' +
  'dark:text-[var(--cosci-text)]';

export const STARTED_COPY_CLASSES = 'reference-started-copy grid gap-[0.1rem]';

export const STARTED_COPY_PARAGRAPH_CLASSES = 'm-0 text-base leading-[1.45]';

export const STARTED_SESSION_CARD_CLASSES =
  'reference-started-session-card grid min-h-[5.3rem] cursor-pointer ' +
  'grid-cols-[minmax(0,1fr)_auto] items-center gap-[1.2rem] rounded-2xl ' +
  'border-0 bg-[linear-gradient(100deg,rgba(16,92,92,0.95),rgba(42,117,95,0.94)),#145d5d] ' +
  'p-[1rem_1rem_1rem_1.35rem] text-left text-white ' +
  'dark:bg-[linear-gradient(100deg,rgba(21,76,76,0.98),rgba(26,92,70,0.96)),#123a3a]';

export const STARTED_SESSION_TITLE_CLASSES =
  'line-clamp-1 text-[1.18rem] leading-[1.25]';

export const STARTED_SESSION_META_CLASSES =
  'mt-[0.3rem] block text-[0.9rem] text-white/80';

export const STARTED_OPEN_CLASSES =
  'reference-started-open min-w-[5.4rem] rounded-full border ' +
  'border-white/75 px-[1.25rem] py-[0.65rem] text-center font-semibold ' +
  'text-white/90';

export const STARTED_NEXT_CLASSES =
  'reference-started-next flex flex-wrap items-center gap-[0.55rem]';

export const STARTED_NEXT_COPY_CLASSES =
  'basis-full m-0 mb-[0.1rem] text-[0.95rem] font-semibold ' +
  'text-[#3c4043] dark:text-[#bdc1c6]';

export const STARTED_NEXT_BUTTON_CLASSES =
  'min-h-[2.6rem] cursor-pointer rounded-full border border-[#1a73e8] ' +
  'bg-transparent px-[1.2rem] font-semibold text-[#1967d2] ' +
  'hover:bg-[#e8f0fe] focus-visible:bg-[#e8f0fe] dark:border-[#7fd7bf] ' +
  'dark:text-[#7fd7bf] dark:hover:bg-[rgba(127,215,191,0.14)] ' +
  'dark:focus-visible:bg-[rgba(127,215,191,0.14)]';

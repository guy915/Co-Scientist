export const HOME_WORKSPACE_CLASSES =
  'cosci-workspace grid h-full min-h-full grid-cols-[minmax(0,1fr)] gap-4 ' +
  'max-[700px]:!h-auto max-[700px]:!min-h-full ' +
  'max-[700px]:!overflow-visible';

export const HOME_WORKSPACE_MAIN_CLASSES =
  'cosci-workspace-main flex h-full min-h-0 min-w-0 flex-col ' +
  'max-[700px]:!h-auto max-[700px]:!min-h-full max-[700px]:!overflow-visible';

export const HOME_STAGE_CLASSES =
  'reference-home-stage box-border grid h-full min-h-0 ' +
  'grid-cols-[minmax(40rem,50.75rem)_minmax(17rem,21rem)] justify-center ' +
  'gap-[clamp(2.5rem,7vw,7.5rem)] overflow-hidden ' +
  'p-[1.15rem_1.5rem_clamp(1.6rem,4vh,2.6rem)] ' +
  'min-[1500px]:!justify-start min-[1500px]:!gap-[clamp(16rem,17.5vw,21rem)] ' +
  'min-[1500px]:!pl-[clamp(17rem,19.25vw,22.5rem)] min-[1500px]:!pr-5 ' +
  'min-[1181px]:[--home-recents-width:clamp(20.75rem,20vw,22rem)] ' +
  'min-[1181px]:!grid min-[1181px]:!h-full min-[1181px]:!min-h-0 ' +
  'min-[1181px]:!items-start min-[1181px]:!overflow-hidden ' +
  'min-[1181px]:!py-0 min-[1181px]:!grid-cols-[minmax(0,1fr)_minmax(20.75rem,var(--home-recents-width))] ' +
  'min-[1181px]:!justify-stretch min-[1181px]:!gap-[clamp(2.25rem,3.1vw,3.35rem)] ' +
  'min-[1181px]:!pl-[clamp(2rem,3vw,4rem)] ' +
  'min-[1181px]:!pr-[clamp(0.7rem,1.2vw,1.3rem)] ' +
  'min-[701px]:max-[1180px]:!h-auto min-[701px]:max-[1180px]:!min-h-full ' +
  'min-[701px]:max-[1180px]:!grid-cols-[minmax(0,1fr)] ' +
  'min-[701px]:max-[1180px]:!justify-items-center ' +
  'min-[701px]:max-[1180px]:!gap-[clamp(1.5rem,3.5vw,2.5rem)] ' +
  'min-[701px]:max-[1180px]:!overflow-visible ' +
  'min-[701px]:max-[1180px]:!p-[clamp(1.5rem,4vw,2.25rem)] ' +
  'max-[700px]:!h-auto max-[700px]:!min-h-full ' +
  'max-[700px]:!grid-cols-[minmax(0,1fr)] max-[700px]:!gap-6 ' +
  'max-[700px]:!overflow-visible ' +
  'max-[700px]:!p-[1.1rem_clamp(0.85rem,4vw,1.2rem)_1.5rem]';

export const HOME_MAIN_CLASSES =
  'reference-home-main grid content-start pt-[clamp(2.4rem,7vh,3.5rem)] ' +
  'min-[1181px]:!h-full min-[1181px]:!min-w-0 ' +
  'min-[1181px]:!max-h-[calc(100vh-4.5rem)] min-[1181px]:!content-start ' +
  'min-[1181px]:!grid-rows-[auto_auto_minmax(2rem,1fr)_auto] ' +
  'min-[1181px]:!pt-[clamp(4.85rem,8.8vh,6.4rem)] ' +
  'min-[1181px]:!pb-[clamp(1.35rem,3.2vh,2.25rem)] ' +
  'min-[701px]:max-[1180px]:!w-[min(100%,43rem)] ' +
  'max-[700px]:!w-[min(100%,21rem)] max-[700px]:!justify-items-stretch ' +
  'max-[700px]:!pt-0 ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!pt-8';

export const HOME_TITLE_CLASSES =
  'mx-auto w-[min(100%,39rem)] text-center text-[clamp(2.75rem,4.2vw,3.2rem)] ' +
  'font-normal leading-[1.13] text-[var(--cosci-home-heading)] ' +
  'min-[1181px]:!w-[min(100%,43.5rem)] ' +
  'min-[1181px]:!text-[clamp(2.35rem,3vw,3rem)] ' +
  'min-[1181px]:!leading-[1.14] max-[700px]:!w-full ' +
  'max-[700px]:!text-[clamp(2rem,10vw,2.45rem)] ' +
  'max-[700px]:!leading-[1.12] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!text-[clamp(2.1rem,2.8vw,2.65rem)]';

export const HOME_STEP_TIMELINE_CLASSES =
  'reference-step-timeline relative m-[clamp(3.7rem,8.5vh,5.2rem)_0_0] grid ' +
  'list-none grid-cols-[repeat(3,minmax(0,1fr))] gap-[3.9rem] p-0 ' +
  'before:absolute before:top-4 before:right-4 before:left-4 before:h-px ' +
  'before:bg-[var(--cosci-step-line)] before:[content:""] ' +
  'min-[1181px]:!grid-cols-[repeat(3,minmax(0,1fr))] ' +
  'min-[1181px]:!gap-x-0 min-[1181px]:!mt-[clamp(3.85rem,7.6vh,5.8rem)] ' +
  'min-[701px]:max-[1180px]:!grid-cols-[repeat(3,minmax(0,1fr))] ' +
  'min-[701px]:max-[1180px]:!gap-0 ' +
  'min-[701px]:max-[1180px]:!mt-[clamp(2.75rem,6vh,4rem)] ' +
  'min-[701px]:max-[1180px]:before:!top-4 ' +
  'min-[701px]:max-[1180px]:before:!right-4 ' +
  'min-[701px]:max-[1180px]:before:!bottom-auto ' +
  'min-[701px]:max-[1180px]:before:!left-4 ' +
  'min-[701px]:max-[1180px]:before:!h-px ' +
  'min-[701px]:max-[1180px]:before:!w-auto ' +
  'max-[700px]:!grid-cols-[minmax(0,1fr)] max-[700px]:!gap-[1.15rem] ' +
  'max-[700px]:!mt-[2.2rem] max-[700px]:before:!top-4 ' +
  'max-[700px]:before:!right-auto max-[700px]:before:!bottom-4 ' +
  'max-[700px]:before:!left-4 max-[700px]:before:!h-auto ' +
  'max-[700px]:before:!w-px ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!mt-[clamp(2.35rem,5.8vh,3.2rem)]';

export const HOME_STEP_ITEM_CLASSES =
  'relative z-[1] grid gap-4 min-[1181px]:!w-[min(100%,15.8rem)] ' +
  'min-[701px]:max-[1180px]:!w-[min(100%,14rem)] ' +
  'min-[701px]:max-[1180px]:!grid-cols-[1fr] ' +
  'min-[701px]:max-[1180px]:!gap-[0.85rem] max-[700px]:!w-full ' +
  'max-[700px]:!grid-cols-[auto_minmax(0,1fr)] max-[700px]:!gap-[0.85rem]';

export const HOME_STEP_ITEM_CENTER_CLASSES = 'min-[701px]:!justify-self-center';

export const HOME_STEP_ITEM_END_CLASSES = 'min-[701px]:!justify-self-end';

export const HOME_STEP_BODY_CLASSES =
  'mt-1 max-w-64 text-[0.96rem] leading-[1.35] text-[var(--cosci-step-text)] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!text-[0.9rem] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!leading-[1.28]';

export const HOME_STEP_NUMBER_CLASSES =
  'grid size-8 place-items-center rounded-full bg-[var(--cosci-step-dot-bg)] ' +
  'text-[0.95rem] font-semibold text-[var(--cosci-step-dot-text)]';

export const HOME_STEP_HEADING_CLASSES =
  'm-0 text-[0.92rem] font-normal text-[var(--cosci-step-heading)]';

export const HOME_SUGGESTION_ROW_CLASSES =
  'reference-suggestion-row mt-[clamp(3.2rem,7vh,4.35rem)] grid ' +
  'grid-cols-[repeat(3,minmax(0,1fr))] gap-[0.85rem] ' +
  'min-[1181px]:!self-end min-[1181px]:!mt-0 ' +
  'min-[701px]:max-[1180px]:!grid-cols-[repeat(3,minmax(0,1fr))] ' +
  'min-[701px]:max-[1180px]:!mt-[clamp(2.75rem,7vh,4.5rem)] ' +
  'max-[700px]:!grid-cols-[minmax(0,1fr)] max-[700px]:!mt-[1.7rem] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!mt-[clamp(2.25rem,5.4vh,3.1rem)]';

export const HOME_SUGGESTION_BUTTON_CLASSES =
  'block h-[4.4rem] min-h-[4.4rem] max-h-[4.4rem] w-full cursor-pointer ' +
  'overflow-hidden rounded-2xl border border-[var(--cosci-suggestion-border)] ' +
  'bg-[var(--cosci-suggestion-bg)] p-[0.9rem_1rem] text-left leading-[1.35] ' +
  'text-[var(--cosci-suggestion-text)] outline-0 [-webkit-box-orient:vertical] ' +
  '[-webkit-line-clamp:2] hover:border-[var(--cosci-suggestion-hover-border)] ' +
  'hover:bg-[var(--cosci-suggestion-active-bg)] ' +
  'focus-visible:border-[var(--cosci-suggestion-hover-border)] ' +
  'focus-visible:bg-[var(--cosci-suggestion-active-bg)] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!min-h-[3.9rem] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!max-h-[3.9rem]';

export const HOME_SUGGESTION_BUTTON_PREVIEWED_CLASSES =
  'border-[var(--cosci-suggestion-hover-border)] ' +
  'bg-[var(--cosci-suggestion-active-bg)]';

export const HOME_SUGGESTION_SLOT_CLASSES =
  'reference-suggestion-slot relative min-w-0 cursor-pointer';

export const HOME_SUGGESTION_PREVIEW_CLASSES =
  'reference-suggestion-preview invisible absolute bottom-[calc(100%+0.5rem)] ' +
  'z-[5] m-0 line-clamp-3 w-max max-w-[min(42rem,calc(100vw-7rem))] ' +
  'translate-y-[0.2rem] overflow-hidden text-[0.84rem] leading-5 font-normal ' +
  'text-[#3c4043] opacity-0 pointer-events-none dark:text-[#e8eaed]';

export const HOME_SUGGESTION_PREVIEW_VISIBLE_CLASSES =
  'visible translate-y-0 opacity-100';

export const HOME_SUGGESTION_PREVIEW_START_CLASSES = 'left-0 text-left';

export const HOME_SUGGESTION_PREVIEW_CENTER_CLASSES =
  'left-1/2 -translate-x-1/2 text-center';

export const HOME_SUGGESTION_PREVIEW_END_CLASSES = 'right-0 text-right';

export const HOME_SUGGESTION_TEXT_CLASSES =
  'reference-suggestion-text line-clamp-2 overflow-hidden leading-[1.35]';

export const HOME_COMPOSER_CLASSES =
  'min-[1181px]:!mt-[clamp(1.25rem,2.4vh,1.9rem)] max-[700px]:!min-h-[6.6rem] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!min-h-[6.35rem]';

export const HOME_COMPOSER_TEXTAREA_CLASSES =
  '[@media(min-width:1181px)_and_(max-height:760px)]:!h-[2.65rem] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!min-h-[2.65rem] ' +
  '[@media(min-width:1181px)_and_(max-height:760px)]:!max-h-[2.65rem]';

export const HOME_RECENTS_PANEL_CLASSES =
  'grid min-h-0 content-start gap-[1.3rem] overflow-hidden pt-1 ' +
  'min-[1181px]:!w-full min-[1181px]:!max-h-[calc(100vh-4.5rem)] ' +
  'min-[1181px]:!justify-self-end min-[1181px]:!overflow-visible ' +
  'min-[1181px]:!pt-[clamp(0.35rem,1vh,0.75rem)] ' +
  'min-[701px]:max-[1180px]:!w-[min(100%,43rem)] ' +
  'min-[701px]:max-[1180px]:!mt-4 max-[700px]:!w-[min(100%,21rem)]';

export const HOME_RECENTS_LIST_CLASSES =
  'grid min-h-0 max-h-[calc(100vh-12rem)] gap-[2.6rem] overflow-y-auto ' +
  'm-0 list-none p-[0_0.6rem_0_0] ' +
  'min-[1181px]:!max-h-[calc(100vh-10.1rem)] min-[1181px]:!m-0 ' +
  'min-[1181px]:!p-[0.55rem_1.2rem_2.15rem_0.55rem] ' +
  'min-[1181px]:![scroll-padding:0.55rem_1.2rem_2.15rem_0.55rem] ' +
  'max-[700px]:!max-h-none max-[700px]:!overflow-visible ' +
  'max-[700px]:!ml-0 max-[700px]:!p-0';

export const HOME_RECENTS_HEADING_ROW_CLASSES =
  'google-recents-heading flex items-center gap-2 ' +
  'text-[var(--md-sys-color-on-surface-variant)]';

export const HOME_LOAD_MORE_ITEM_CLASSES =
  'reference-load-more-item flex justify-center pt-1 pb-2';

export const HOME_LOAD_MORE_BUTTON_CLASSES =
  'reference-load-more justify-self-center border-0 bg-transparent px-2 py-1 ' +
  'font-[inherit] text-[0.9rem] font-medium text-[var(--idea-ref-blue)] ' +
  'hover:underline focus-visible:underline dark:text-[var(--cosci-blue)]';

export const HOME_TOAST_CLASSES =
  'reference-toast fixed top-1/2 left-1/2 z-[60] -translate-x-1/2 ' +
  '-translate-y-1/2 rounded bg-[#303134] px-5 py-[0.82rem] text-[0.92rem] ' +
  'font-medium text-[#f1f3f4] shadow-[0_1px_2px_rgba(0,0,0,0.18),0_4px_10px_rgba(0,0,0,0.22)] ' +
  'dark:bg-[#f1f3f4] dark:text-[#202124]';

export const COMPOSER_BASE_CLASSES =
  'reference-composer relative mt-4 min-h-[7.9rem] rounded-[1.7rem] border ' +
  'border-[var(--cosci-composer-border)] bg-[var(--cosci-composer-bg)] ' +
  'p-[1.25rem_1.5rem_0.8rem] shadow-[var(--cosci-composer-shadow)]';

export const COMPOSER_LABEL_CLASSES = 'relative block min-h-[3.6rem]';

export const COMPOSER_LABEL_TEXT_CLASSES =
  'absolute top-0 left-0 z-[1] flex h-6 items-center gap-[0.45rem] ' +
  'pointer-events-none text-base text-[var(--cosci-composer-label)]';

export const COMPOSER_LABEL_TEXT_HIDDEN_CLASSES = 'hidden';

export const COMPOSER_LABEL_ICON_CLASSES = 'text-[1.15rem]';

export const COMPOSER_TEXTAREA_CLASSES =
  'relative z-[2] block h-[3.6rem] max-h-[3.6rem] min-h-[3.6rem] w-full ' +
  'resize-none border-0 bg-transparent pt-0 font-[inherit] leading-6 ' +
  'text-[var(--cosci-composer-text)] outline-none';

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
  'bg-transparent p-0 text-[var(--cosci-source-button)] ' +
  'hover:bg-[var(--cosci-source-button-hover-bg)] ' +
  'hover:text-[var(--cosci-source-button-hover)] ' +
  'focus-visible:bg-[var(--cosci-source-button-hover-bg)] ' +
  'focus-visible:text-[var(--cosci-source-button-hover)] ' +
  'aria-expanded:bg-[var(--cosci-source-button-hover-bg)] ' +
  'aria-expanded:text-[var(--cosci-source-button-hover)]';

export const COMPOSER_SOURCE_ICON_CLASSES = 'text-xl';

export const COMPOSER_SUBMIT_BUTTON_CLASSES =
  'pointer-events-auto grid size-10 cursor-pointer place-items-center ' +
  'rounded-full border-0 bg-transparent p-0 text-[var(--cosci-composer-submit)] ' +
  'disabled:cursor-default disabled:text-[var(--cosci-composer-submit-disabled)]';

export const CONNECTORS_MENU_CLASSES =
  'reference-connectors-menu pointer-events-auto absolute bottom-[2.45rem] ' +
  'left-[2.35rem] z-10 w-56 overflow-hidden rounded-[0.9rem] border ' +
  'border-[var(--cosci-menu-border)] bg-[var(--cosci-menu-bg)] py-[0.45rem] ' +
  'text-[var(--cosci-menu-text)] shadow-[var(--cosci-menu-shadow)]';

export const CONNECTORS_MENU_HEADER_CLASSES =
  'reference-connectors-menu-row reference-connectors-menu-row--top grid ' +
  'min-h-[2.6rem] w-full grid-cols-[1fr] items-center border-0 border-b ' +
  'border-[var(--cosci-menu-divider)] bg-transparent px-[0.9rem] py-[0.45rem] ' +
  'font-medium text-inherit';

export const CONNECTORS_MENU_ROW_CLASSES =
  'reference-connectors-menu-row grid min-h-[2.6rem] w-full cursor-pointer ' +
  'grid-cols-[1.35rem_1fr_auto] items-center gap-3 border-0 bg-transparent ' +
  'px-[0.9rem] py-[0.45rem] text-left font-[inherit] text-[0.9rem] ' +
  'text-inherit hover:bg-[var(--cosci-menu-row-hover)] ' +
  'focus-visible:bg-[var(--cosci-menu-row-hover)] focus-visible:outline-none';

export const CONNECTOR_ICON_CLASSES =
  'reference-connector-icon font-["Material_Symbols_Outlined"] text-[1.15rem] ' +
  'text-[var(--cosci-menu-icon)] [font-variation-settings:"FILL"_0,"wght"_400,"GRAD"_0,"opsz"_24]';

export const CONNECTOR_TOGGLE_BASE_CLASSES =
  'reference-toggle relative h-[0.95rem] w-[1.6rem] rounded-full ' +
  'after:absolute after:top-[0.15rem] after:size-[0.65rem] ' +
  'after:rounded-full after:[content:""]';

export const CONNECTOR_TOGGLE_ON_CLASSES =
  'bg-[#d2e3fc] after:right-[0.18rem] after:bg-[#1a73e8]';

export const CONNECTOR_TOGGLE_OFF_CLASSES =
  'bg-[#dadce0] after:left-[0.18rem] after:bg-[#80868b]';

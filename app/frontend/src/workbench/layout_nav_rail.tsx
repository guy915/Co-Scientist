import type {RefObject} from 'react';
import {Link} from 'react-router-dom';
import {Icon, type IconName} from '@/components/icon';
import {isModifiedClick} from '@/workbench/dom_events';
import {
  SETTINGS_SECTIONS,
  type SettingsSection,
} from './components/settings_dialog';
import type {ShellPanel} from './layout';
import {NAV_ICON_CLASSES, ShellPopover} from './layout_primitives';
import {tooltipClassNames} from './classes';
import type {ChatSummary} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {TruncatedLabel} from './components/truncated_label';
import {useFittingRows, useOverflowing} from './hooks/dom';
import {preferredSessionSide} from './layout_session_switch';
import {tabPath} from './run_tabs';

// Re-exported so `ChatRailData` keeps its long-standing import site (the
// shell reads it from the rail, not from the list module it now lives in).

// The constants below pair a CSS class for the "open" rail state with one
// for the "collapsed"/default state; each pair is selected at render time by
// the single `navOpen` boolean (see NAV_RAIL_VARIANTS below). The actual
// responsive behavior (desktop icon rail vs mobile off-canvas drawer,
// iOS-safe viewport sizing) lives in shell_surface.css, keyed off the
// `nav-open` / `nav-collapsed` shell classes and the ~700px breakpoint.
const NAV_PANEL_OPEN_CLASSES = 'ucs-nav-panel ucs-nav-panel--open';

const NAV_PANEL_COLLAPSED_CLASSES = 'ucs-nav-panel ucs-nav-panel--collapsed';

const NAV_GROUP_OPEN_CLASSES = 'ucs-nav-top ucs-nav-top--open';

const NAV_GROUP_COLLAPSED_CLASSES = 'ucs-nav-top ucs-nav-top--collapsed';

const NAV_ITEMS_OPEN_CLASSES = 'ucs-nav-items ucs-nav-items--open';

const NAV_ITEMS_COLLAPSED_CLASSES = 'ucs-nav-items ucs-nav-items--collapsed';

const NAV_BOTTOM_CLASSES = 'ucs-nav-bottom ucs-nav-bottom--open';

const NAV_BOTTOM_COLLAPSED_CLASSES = 'ucs-nav-bottom ucs-nav-bottom--collapsed';

const NAV_ITEM_OPEN_CLASSES = 'ucs-nav-item ucs-nav-item--open';

const NAV_ITEM_COLLAPSED_CLASSES = 'ucs-nav-item ucs-nav-item--collapsed';

const NAV_LABEL_OPEN_CLASSES = 'nav-label nav-label--open';

const NAV_LABEL_COLLAPSED_CLASSES = 'nav-label nav-label--collapsed';

const RAIL_POPOVER_CLASSES = 'ucs-popover--rail';

const SETTINGS_CONTROL_CLASSES = 'ucs-settings-control';

const SETTINGS_MENU_CLASSES = 'ucs-settings-menu';

const SETTINGS_MENU_ITEM_CLASSES = 'ucs-settings-menu-item';

const SETTINGS_MENU_ICON_CLASSES = 'ucs-settings-menu-icon';

const SIDE_CONTENT_CLASSES = 'ucs-side-content';

const SIDE_CONTENT_OPEN_CLASSES = 'ucs-side-content--open';

const SIDE_CONTENT_COLLAPSED_CLASSES = 'ucs-side-content--collapsed';

// Per-region class bundles for the rail's expanded vs collapsed presentation,
// keyed by the single `navOpen` flag (see NavRail below). Replaces what would
// otherwise be parallel `navOpen ? ... : ...` ternaries with one lookup.
const NAV_RAIL_VARIANTS = {
  open: {
    panel: NAV_PANEL_OPEN_CLASSES,
    group: NAV_GROUP_OPEN_CLASSES,
    items: NAV_ITEMS_OPEN_CLASSES,
    bottom: NAV_BOTTOM_CLASSES,
    item: NAV_ITEM_OPEN_CLASSES,
    label: NAV_LABEL_OPEN_CLASSES,
    sideContent: `${SIDE_CONTENT_CLASSES} ${SIDE_CONTENT_OPEN_CLASSES}`,
    settingsControl: `${SETTINGS_CONTROL_CLASSES} ucs-settings-control--open`,
  },
  collapsed: {
    panel: NAV_PANEL_COLLAPSED_CLASSES,
    group: NAV_GROUP_COLLAPSED_CLASSES,
    items: NAV_ITEMS_COLLAPSED_CLASSES,
    bottom: NAV_BOTTOM_COLLAPSED_CLASSES,
    item: NAV_ITEM_COLLAPSED_CLASSES,
    label: NAV_LABEL_COLLAPSED_CLASSES,
    sideContent: `${SIDE_CONTENT_CLASSES} ${SIDE_CONTENT_COLLAPSED_CLASSES}`,
    settingsControl:
      `${SETTINGS_CONTROL_CLASSES} ` + 'ucs-settings-control--collapsed',
  },
} as const;

// One rail variant's class bundle (see NAV_RAIL_VARIANTS above).
type NavRailVariant =
  (typeof NAV_RAIL_VARIANTS)[keyof typeof NAV_RAIL_VARIANTS];

// The rail's top group: Menu toggle, New chat, and the chat-history
// sidebar. Split out of NavRail so the component itself stays a thin
// wrapper around this and the bottom Settings control.
interface NavRailTopProps {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  rail: ChatRailData;
  nav: NavRailVariant;
}

function NavRailTop({
  navOpen,
  toggleNav,
  startNewChat,
  rail,
  nav,
}: NavRailTopProps) {
  return (
    <div className={nav.group}>
      <NavActionButton
        label="Menu"
        icon="menu"
        className={nav.item}
        labelClassName={nav.label}
        expanded={navOpen}
        controls="primary-navigation"
        onClick={toggleNav}
      />
      <nav id="primary-navigation" className={nav.items}>
        <NavNewChatLink
          className={nav.item}
          labelClassName={nav.label}
          onNewChat={startNewChat}
        />
      </nav>
      <ChatHistorySidebar sideContentClasses={nav.sideContent} rail={rail} />
    </div>
  );
}

/**
 * Renders the icon rail: Menu toggle, New chat, the chat-history sidebar,
 * and the bottom Settings control. All open/collapsed presentation is
 * derived here (and in the sub-components below) from the single `navOpen`
 * flag.
 *
 * @param navOpen Whether the rail is expanded (desktop) or open (mobile).
 * @param toggleNav Toggles the rail/drawer.
 * @param startNewChat Resets the chat workspace and navigates home.
 * @param rail The chat list, its expansion flag, and what to highlight.
 * @param activePanel The currently open popover, if any.
 * @param onTogglePanel Opens/closes the given popover.
 * @param onOpenSettings Opens the full-screen Settings dialog at a section.
 * @param settingsControlRef Anchor ref for outside-click dismissal of the
 *   Settings popover.
 */
interface NavRailProps {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  rail: ChatRailData;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  onOpenSettings: (section: SettingsSection) => void;
  settingsControlRef: RefObject<HTMLDivElement | null>;
}

export function NavRail({
  navOpen,
  toggleNav,
  startNewChat,
  rail,
  activePanel,
  onTogglePanel,
  onOpenSettings,
  settingsControlRef,
}: NavRailProps) {
  const nav = navOpen ? NAV_RAIL_VARIANTS.open : NAV_RAIL_VARIANTS.collapsed;

  return (
    <aside className={nav.panel} aria-label="Primary navigation">
      <NavRailTop
        navOpen={navOpen}
        toggleNav={toggleNav}
        startNewChat={startNewChat}
        rail={rail}
        nav={nav}
      />
      <div className={nav.bottom}>
        <RailSettingsControl
          nav={nav}
          activePanel={activePanel}
          onTogglePanel={onTogglePanel}
          onOpenSettings={onOpenSettings}
          settingsControlRef={settingsControlRef}
        />
      </div>
    </aside>
  );
}

// The Settings popover menu itself, shown while the rail's Settings control
// is the active panel. Its rows come from the dialog's own SETTINGS_SECTIONS
// so the menu and the dialog's section rail always agree.
function SettingsPopoverMenu({
  onOpenSettings,
}: {
  onOpenSettings: (section: SettingsSection) => void;
}) {
  return (
    <ShellPopover className={`${RAIL_POPOVER_CLASSES} ucs-popover--menu`}>
      <div className={SETTINGS_MENU_CLASSES} role="menu">
        {SETTINGS_SECTIONS.map(({label, icon, section}) => (
          <SettingsMenuButton
            key={section}
            label={label}
            icon={icon}
            onClick={() => onOpenSettings(section)}
          />
        ))}
      </div>
    </ShellPopover>
  );
}

// The Settings control at the bottom of the rail: the trigger button plus
// its popover menu (Appearance/Model/Help). Takes the resolved class bundle
// rather than `navOpen`, so the open/collapsed lookup happens once, in
// NavRail, and cannot disagree with the rail it sits in.
function RailSettingsControl({
  nav,
  activePanel,
  onTogglePanel,
  onOpenSettings,
  settingsControlRef,
}: {
  nav: NavRailVariant;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  onOpenSettings: (section: SettingsSection) => void;
  settingsControlRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div ref={settingsControlRef} className={nav.settingsControl}>
      <NavActionButton
        label="Settings"
        icon="settings"
        className={nav.item}
        labelClassName={nav.label}
        expanded={activePanel === 'settings'}
        onClick={() => onTogglePanel('settings')}
      />
      {activePanel === 'settings' && (
        <SettingsPopoverMenu onOpenSettings={onOpenSettings} />
      )}
    </div>
  );
}

// The rail's "New chat" action. A real link, so Cmd/middle-clicking it opens
// a fresh workspace in a new tab like every other navigation here; the reset
// still runs on a plain click, and only on a plain click -- see
// isModifiedClick.
function NavNewChatLink({
  className,
  labelClassName,
  onNewChat,
}: {
  className: string;
  labelClassName: string;
  onNewChat: () => void;
}) {
  return (
    <Link
      to="/"
      state={{cosciAction: 'new-chat'}}
      className={tooltipClassNames({className, placement: 'right'})}
      aria-label="New chat"
      data-tooltip="New chat"
      onClick={event => {
        if (!isModifiedClick(event)) onNewChat();
      }}
    >
      <Icon
        aria-hidden="true"
        className={NAV_ICON_CLASSES}
        name="edit_square"
      />
      <span className={labelClassName}>New chat</span>
    </Link>
  );
}

// A single rail action (Menu/hamburger, Settings): an icon plus a label that
// is visually collapsed to icon-only via `labelClassName` when the rail is
// collapsed, with the full label still exposed to assistive tech through
// aria-label/data-tooltip.
function NavActionButton({
  label,
  icon,
  className,
  labelClassName,
  expanded,
  controls,
  onClick,
}: {
  label: string;
  icon: IconName;
  className: string;
  labelClassName: string;
  expanded?: boolean;
  controls?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({className, placement: 'right'})}
      aria-label={label}
      data-tooltip={label}
      aria-expanded={expanded}
      aria-controls={controls}
      onClick={onClick}
    >
      <Icon aria-hidden="true" className={NAV_ICON_CLASSES} name={icon} />
      <span className={labelClassName}>{label}</span>
    </button>
  );
}

// One row inside the Settings popover menu (Appearance/Model/Help); onClick
// is wired by the caller to openSettings(section).
function SettingsMenuButton({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: IconName;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={SETTINGS_MENU_ITEM_CLASSES}
      role="menuitem"
      onClick={onClick}
    >
      <Icon
        aria-hidden="true"
        className={SETTINGS_MENU_ICON_CLASSES}
        name={icon}
      />
      <span>{label}</span>
    </button>
  );
}

const SIDE_HEADING_CLASSES = 'ucs-side-heading';

const CHAT_LIST_CLASSES = 'ucs-chat-list';

// Applied only while the list has more chats than the rail can show, since it
// turns the list into a scroll container (which clips its tooltips).
const CHAT_LIST_SCROLLABLE_CLASSES = 'ucs-chat-list--scrollable';

const CHAT_HISTORY_LINK_CLASSES = 'ucs-chat-link';

const CHAT_HISTORY_LINK_ACTIVE_CLASSES = 'ucs-chat-link--active';

const CHAT_HISTORY_LABEL_CLASSES = 'ucs-chat-label';

const CHAT_HISTORY_MORE_CLASSES = 'ucs-chat-more';

/**
 * The chat-list state the rail renders, threaded whole through NavRail so
 * each level passes one value instead of five.
 */
export interface ChatRailData {
  chats: ChatSummary[];
  /** The chat being viewed on /chats/:id, if any. */
  activeChatId: string | undefined;
  /** The run being viewed on /runs/:id, so its chat stays highlighted. */
  activeRunId: string | undefined;
  showAllChats: boolean;
  onToggleShowAllChats: () => void;
}

// Whether a chat row is the one currently being viewed -- either opened
// directly, or through the run it started.
function isActiveChat(chat: ChatSummary, rail: ChatRailData): boolean {
  if (rail.activeChatId) return chat.id === rail.activeChatId;
  return Boolean(chat.run_id) && chat.run_id === rail.activeRunId;
}

/**
 * Where a chat row leads: wherever this reader last had the Chat/Results
 * switch on for this session, defaulting to the stage the session has
 * actually reached.
 *
 * A session that has started a run has moved past its conversation, so by
 * default the row opens the run -- which is the live progress view while it
 * executes and the report once it lands, chosen by the run page itself.
 * Reopening the transcript instead put every session, running or long
 * finished, back at the same settled prompt and made the rail read as a list
 * of drafts. That default yields to memory once the reader has actually used
 * the header's Chat/Results switch (see layout_session_memory) -- only a chat
 * that never started a run, or one with no recorded side yet, opens by the
 * rule above.
 */
function chatPath(chat: ChatSummary): string {
  if (!chat.run_id) return `/chats/${chat.id}`;
  return preferredSessionSide(chat.run_id) === 'chat'
    ? `/chats/${chat.id}`
    : tabPath(chat.run_id, undefined);
}

// One row in the "Chats" list: the chat's generated title, falling back to a
// concise clause of the scientist's challenge.
function ChatHistoryLink({
  chat,
  isActive,
}: {
  chat: ChatSummary;
  isActive: boolean;
}) {
  return (
    <Link
      data-fitting-row=""
      to={chatPath(chat)}
      className={tooltipClassNames({
        className: isActive
          ? `${CHAT_HISTORY_LINK_CLASSES} ${CHAT_HISTORY_LINK_ACTIVE_CLASSES}`
          : CHAT_HISTORY_LINK_CLASSES,
        placement: 'right',
        wrap: true,
      })}
      aria-current={isActive ? 'page' : undefined}
      data-tooltip={chat.challenge}
    >
      <TruncatedLabel
        className={CHAT_HISTORY_LABEL_CLASSES}
        text={chat.title?.trim() || conciseTitle(chat.challenge)}
      />
    </Link>
  );
}

// The "Show more"/"Show less" toggle at the bottom of the chat list.
function ShowMoreChatsButton({
  showAllChats,
  onToggle,
}: {
  showAllChats: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={CHAT_HISTORY_MORE_CLASSES}
      onClick={onToggle}
    >
      {showAllChats ? 'Show less' : 'Show more'}
      <Icon
        aria-hidden="true"
        name={showAllChats ? 'expand_less' : 'expand_more'}
      />
    </button>
  );
}

// The scrollable chat list itself, plus the "Show more"/"Show less" toggle
// when the history exceeds what fits. Split out of ChatHistorySidebar so the
// overflow-tracking ref/state (only ever read by this list) stays local to
// the piece that uses it.
interface ChatListProps {
  visibleChats: ChatSummary[];
  rail: ChatRailData;
  hasExtraChats: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
}

function ChatList({visibleChats, rail, hasExtraChats, listRef}: ChatListProps) {
  // Only scroll the list when the rail cannot fit it. A scroll container clips
  // its content even with no scrollbar showing, which would cut off the
  // chat-link tooltips escaping to the right.
  const [chatListRef, chatListOverflows] = useOverflowing<HTMLDivElement>();

  return (
    <div
      // One element, two measurements: the overflow probe decides whether it
      // scrolls, the fitting probe (owned by the parent) decides how many rows
      // it is handed.
      ref={node => {
        chatListRef.current = node;
        listRef.current = node;
      }}
      className={
        chatListOverflows
          ? `${CHAT_LIST_CLASSES} ${CHAT_LIST_SCROLLABLE_CLASSES}`
          : CHAT_LIST_CLASSES
      }
    >
      {visibleChats.map(chat => (
        <ChatHistoryLink
          key={chat.id}
          chat={chat}
          isActive={isActiveChat(chat, rail)}
        />
      ))}
      {hasExtraChats && (
        <ShowMoreChatsButton
          showAllChats={rail.showAllChats}
          onToggle={rail.onToggleShowAllChats}
        />
      )}
    </div>
  );
}

/**
 * The "Chats" section of the rail: the chat list, capped to what the rail
 * actually has room for until expanded, with the active chat highlighted.
 *
 * @param sideContentClasses The rail's open/collapsed section classes, passed
 *   in so this module stays independent of the rail's variant table.
 * @param rail The chats, the expansion flag, and what to highlight.
 */
export function ChatHistorySidebar({
  sideContentClasses,
  rail,
}: {
  sideContentClasses: string;
  rail: ChatRailData;
}) {
  const {containerRef, listRef, visibleCount} = useFittingRows<
    HTMLDivElement,
    HTMLDivElement
  >();
  const visibleChats = rail.showAllChats
    ? rail.chats
    : rail.chats.slice(0, visibleCount);
  const hasExtraChats = rail.chats.length > visibleChats.length;

  return (
    <div ref={containerRef} className={sideContentClasses}>
      <p className={SIDE_HEADING_CLASSES}>Chats</p>
      <ChatList
        visibleChats={visibleChats}
        rail={rail}
        hasExtraChats={hasExtraChats || rail.showAllChats}
        listRef={listRef}
      />
    </div>
  );
}

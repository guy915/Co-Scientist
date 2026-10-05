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
import type {ChatSummary, Run} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {TruncatedLabel} from './components/truncated_label';
import {useFittingRows, useOverflowing} from './hooks/dom';
import {preferredSessionSide} from './layout_session_switch';
import {tabPath} from './run_tabs';

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

type NavRailVariant =
  (typeof NAV_RAIL_VARIANTS)[keyof typeof NAV_RAIL_VARIANTS];

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

// Only ordinary navigation resets the current chat; modified clicks must leave
// this tab unchanged.
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

// Collapsed labels retain their accessible names through aria-label.
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

// Scroll containers clip tooltips even without visible scrollbars; enable
// scrolling only when needed.
const CHAT_LIST_SCROLLABLE_CLASSES = 'ucs-chat-list--scrollable';

const CHAT_HISTORY_LINK_CLASSES = 'ucs-chat-link';

const CHAT_HISTORY_LINK_ACTIVE_CLASSES = 'ucs-chat-link--active';

const CHAT_HISTORY_LABEL_CLASSES = 'ucs-chat-label';

const CHAT_HISTORY_MORE_CLASSES = 'ucs-chat-more';

export interface ChatRailData {
  chats: ChatSummary[];
  activeChatId: string | undefined;
  activeRunId: string | undefined;
  showAllChats: boolean;
  onToggleShowAllChats: () => void;
}

function isActiveChat(chat: ChatSummary, rail: ChatRailData): boolean {
  if (rail.activeChatId) return chat.id === rail.activeChatId;
  return Boolean(chat.run_id) && chat.run_id === rail.activeRunId;
}

const EXAMPLE_ENTRY_PREFIX = 'example:';

// Examples list in Chats for every visitor, so phones reach them too; an
// opened example lists as its private copy instead.
export function withExamples(
  chats: ChatSummary[],
  history: Run[],
): ChatSummary[] {
  const opened = new Set(
    history.map(run => run.config.example_source_id).filter(Boolean),
  );
  const entries = history
    .filter(run => run.is_demo && !opened.has(run.id))
    .map(run => ({
      id: `${EXAMPLE_ENTRY_PREFIX}${run.id}`,
      title: run.title ?? null,
      challenge: run.research_goal,
      status: 'completed' as const,
      run_id: null,
      created_at: run.created_at,
      updated_at: run.updated_at,
    }));
  return [...chats, ...entries];
}

// Started sessions default to their run; explicit last-viewed side takes
// precedence so history reopens where the reader left off.
function chatPath(chat: ChatSummary): string {
  if (chat.id.startsWith(EXAMPLE_ENTRY_PREFIX))
    return `/examples/${chat.id.slice(EXAMPLE_ENTRY_PREFIX.length)}`;
  if (!chat.run_id) return `/chats/${chat.id}`;
  return preferredSessionSide(chat.run_id) === 'chat'
    ? `/chats/${chat.id}`
    : tabPath(chat.run_id, undefined);
}

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

interface ChatListProps {
  visibleChats: ChatSummary[];
  rail: ChatRailData;
  hasExtraChats: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
}

function ChatList({visibleChats, rail, hasExtraChats, listRef}: ChatListProps) {
  // Only overflowing lists may scroll: otherwise their container would clip
  // escaping chat tooltips.
  const [chatListRef, chatListOverflows] = useOverflowing<HTMLDivElement>();

  return (
    <div
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

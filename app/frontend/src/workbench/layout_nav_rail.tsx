import type {RefObject} from 'react';
import {Link} from 'react-router-dom';
import {Button, Menu, MenuItem, NavItemButton, NavItemLink} from '@/shared/ui';
import {isModifiedClick} from '@/workbench/dom_events';
import {
  SETTINGS_SECTIONS,
  type SettingsSection,
} from './components/settings_dialog';
import type {ShellPanel} from './layout';
import {joinClasses, tooltipClassNames} from './classes';
import type {ChatSummary, Run} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {TruncatedLabel} from './components/truncated_label';
import {useFittingRows, useOverflowing} from './hooks/dom';
import {preferredSessionSide} from './layout_session_switch';
import {tabPath} from './run_tabs';

const RAIL_MENU_LAYOUT_CLASSES =
  'absolute z-[35] origin-bottom-left bottom-[0.15rem] left-[3rem] w-[min(13.5rem,calc(100vw-4rem))] ' +
  '[@media(max-width:700px)]:fixed [@media(max-width:700px)]:right-auto ' +
  '[@media(max-width:700px)]:bottom-[1.15rem] [@media(max-width:700px)]:left-[0.5rem] ' +
  '[@media(max-width:700px)]:w-[min(13.5rem,calc(100vw-1rem))]';

const SETTINGS_CONTROL_CLASSES =
  'relative grid w-auto justify-items-center [@media(max-width:700px)]:w-full';

// Rail rules resolve per width band: bare classes are the base,
// `min-[701px]:` the desktop rail and `[@media(max-width:700px)]:` the phone
// drawer. Fractional widths between the two bands keep the base.
// The panel stacks above the workspace so navigation popups are not covered.
// Phones stretch it to the inset edges: iOS Safari vh would hide the drawer's
// bottom under its toolbar.
// `ucs-nav-panel` scopes the shell tones for its buttons (tokens.css).
const NAV_PANEL_CLASSES =
  'ucs-nav-panel relative z-[70] box-border flex h-[100vh] w-full flex-col items-center justify-between [border-right:0] bg-cosci-rail py-[1.25rem] ' +
  '[@media(max-width:700px)]:fixed [@media(max-width:700px)]:[inset:0_auto_0_0] [@media(max-width:700px)]:z-[60] ' +
  '[@media(max-width:700px)]:h-auto [@media(max-width:700px)]:w-[21rem] [@media(max-width:700px)]:min-w-0 [@media(max-width:700px)]:max-w-[85vw] ' +
  '[@media(max-width:700px)]:items-stretch [@media(max-width:700px)]:px-[0.75rem] [@media(max-width:700px)]:py-[1rem] ' +
  '[@media(max-width:700px)]:rounded-r-workspace';

const NAV_GROUP_PHONE_CLASSES =
  '[@media(max-width:700px)]:flex [@media(max-width:700px)]:min-h-0 [@media(max-width:700px)]:w-full [@media(max-width:700px)]:flex-1 ' +
  '[@media(max-width:700px)]:flex-col [@media(max-width:700px)]:items-stretch [@media(max-width:700px)]:[justify-items:stretch] [@media(max-width:700px)]:gap-[0.3rem] [@media(max-width:700px)]:overflow-hidden';

const NAV_BOTTOM_CLASSES =
  'relative grid items-center justify-items-center gap-[0.8rem] p-0 ' +
  '[@media(max-width:700px)]:w-full [@media(max-width:700px)]:items-stretch [@media(max-width:700px)]:[justify-items:stretch] [@media(max-width:700px)]:gap-[0.3rem]';

const SIDE_CONTENT_CLASSES =
  'mt-[1rem] grid max-h-[22rem] min-w-0 gap-[0.35rem] ' +
  'min-[701px]:flex min-[701px]:min-h-0 min-[701px]:max-h-none min-[701px]:flex-1 min-[701px]:flex-col ' +
  '[@media(max-width:700px)]:flex [@media(max-width:700px)]:min-h-0 [@media(max-width:700px)]:max-h-none [@media(max-width:700px)]:flex-1 ' +
  '[@media(max-width:700px)]:flex-col [@media(max-width:700px)]:overflow-hidden';

// Children inherit the closed phone drawer's visibility:hidden, which keeps its
// chat links out of the tab order; none may set `visible` on phones.
const NAV_RAIL_VARIANTS = {
  open: {
    panel: joinClasses(
      NAV_PANEL_CLASSES,
      'min-[701px]:items-stretch min-[701px]:px-[0.75rem] min-[701px]:py-[1rem]',
      '[@media(max-width:700px)]:visible [@media(max-width:700px)]:[transform:translateX(0)]',
      '[@media(max-width:700px)]:shadow-drawer',
      '[@media(max-width:700px)]:[transition:transform_var(--motion-duration-long)_var(--motion-ease-standard)] [@media(max-width:700px)]:motion-reduce:[transition:none]',
    ),
    group: joinClasses(
      'grid gap-[0.85rem] min-[701px]:flex min-[701px]:min-h-0 min-[701px]:w-full min-[701px]:flex-1 min-[701px]:flex-col',
      'min-[701px]:items-stretch min-[701px]:gap-[0.25rem] min-[701px]:mt-[0.25rem]',
      NAV_GROUP_PHONE_CLASSES,
    ),
    bottom: NAV_BOTTOM_CLASSES,
    sideContent: SIDE_CONTENT_CLASSES,
    settingsControl: `${SETTINGS_CONTROL_CLASSES} min-[701px]:w-full`,
  },
  collapsed: {
    // Hidden after the slide-out so the closed drawer leaves the tab order
    // and the accessibility tree.
    panel: joinClasses(
      NAV_PANEL_CLASSES,
      'min-[701px]:py-[1rem] [@media(max-width:700px)]:invisible [@media(max-width:700px)]:[transform:translateX(-100%)]',
      '[@media(max-width:700px)]:[transition:transform_var(--motion-duration-long)_var(--motion-ease-standard),visibility_0s_linear_var(--motion-duration-long)] [@media(max-width:700px)]:motion-reduce:[transition:none]',
    ),
    group: joinClasses(
      'grid w-full items-center justify-items-center gap-[0.74rem] min-[701px]:gap-[0.25rem] min-[701px]:mt-[0.25rem]',
      NAV_GROUP_PHONE_CLASSES,
    ),
    bottom: joinClasses(
      NAV_BOTTOM_CLASSES,
      'min-[701px]:w-full min-[701px]:gap-[0.74rem]',
    ),
    sideContent: joinClasses(
      SIDE_CONTENT_CLASSES,
      'min-[701px]:mt-0 min-[701px]:opacity-0 min-[701px]:invisible',
    ),
    settingsControl: SETTINGS_CONTROL_CLASSES,
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
      <NavItemButton
        label="Menu"
        icon="menu"
        open={navOpen}
        expanded={navOpen}
        controls="primary-navigation"
        onClick={toggleNav}
      />
      {/* display:contents keeps navigation semantics while giving all controls
          one grid gap source, so the first item carries the separation. */}
      <nav id="primary-navigation" className="contents">
        <NavNewChatLink open={navOpen} onNewChat={startNewChat} />
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
          open={navOpen}
          activePanel={activePanel}
          onTogglePanel={onTogglePanel}
          onOpenSettings={onOpenSettings}
          settingsControlRef={settingsControlRef}
        />
      </div>
    </aside>
  );
}

function RailSettingsControl({
  nav,
  open,
  activePanel,
  onTogglePanel,
  onOpenSettings,
  settingsControlRef,
}: {
  nav: NavRailVariant;
  open: boolean;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  onOpenSettings: (section: SettingsSection) => void;
  settingsControlRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div ref={settingsControlRef} className={nav.settingsControl}>
      <NavItemButton
        label="Settings"
        icon="settings"
        open={open}
        expanded={activePanel === 'settings'}
        onClick={() => onTogglePanel('settings')}
      />
      <Menu
        open={activePanel === 'settings'}
        onClose={() => onTogglePanel('settings')}
        label="Settings"
        anchorRefs={[settingsControlRef]}
        layoutClassName={RAIL_MENU_LAYOUT_CLASSES}
      >
        {SETTINGS_SECTIONS.map(({label, icon, section}) => (
          <MenuItem
            key={section}
            icon={icon}
            onClick={() => onOpenSettings(section)}
          >
            {label}
          </MenuItem>
        ))}
      </Menu>
    </div>
  );
}

// Only ordinary navigation resets the current chat; modified clicks must leave
// this tab unchanged.
function NavNewChatLink({
  open,
  onNewChat,
}: {
  open: boolean;
  onNewChat: () => void;
}) {
  return (
    <NavItemLink
      to="/"
      state={{cosciAction: 'new-chat'}}
      icon="edit_square"
      label="New chat"
      open={open}
      layoutClassName="mt-[0.5rem]"
      onClick={event => {
        if (!isModifiedClick(event)) onNewChat();
      }}
    />
  );
}

const SIDE_HEADING_CLASSES =
  'mx-0 mt-[1.15rem] mb-[0.55rem] px-[0.75rem] text-[0.875rem] font-medium text-cosci-fg';

// Row height and gap must stay in rem: hooks/dom.ts FALLBACK_ROW_PITCH_PX is
// the 2.35rem link line-height plus this 0.35rem gap at a 16px root.
const CHAT_LIST_CLASSES =
  'ucs-chat-list grid min-w-0 gap-[0.35rem] min-[701px]:min-h-0 ' +
  '[@media(max-width:700px)]:grid-cols-[minmax(0,1fr)] [@media(max-width:700px)]:[align-content:start] [@media(max-width:700px)]:min-h-0 ' +
  '[@media(max-width:700px)]:flex-1 [@media(max-width:700px)]:overflow-x-hidden [@media(max-width:700px)]:overflow-y-auto';

// Scroll containers clip tooltips even without visible scrollbars; enable
// scrolling only when needed.
const CHAT_LIST_SCROLLABLE_CLASSES =
  'min-[701px]:overflow-x-hidden min-[701px]:overflow-y-auto';

const CHAT_HISTORY_LINK_CLASSES =
  'flex min-h-[2.35rem] min-w-0 items-center rounded-full px-[0.75rem] text-[0.875rem] leading-[2.35rem] no-underline';

const CHAT_HISTORY_LINK_IDLE_CLASSES =
  'text-cosci-shell-icon [&:hover]:bg-cosci-shell-hover-bg [&:hover]:text-cosci-fg focus-visible:bg-cosci-shell-hover-bg focus-visible:text-cosci-fg';

const CHAT_HISTORY_LINK_ACTIVE_CLASSES =
  'bg-cosci-shell-hover-bg text-cosci-fg';

// Measure labels against the full available width, not their already-truncated
// text, or fitting collapses the label.
const CHAT_HISTORY_LABEL_CLASSES =
  'min-w-0 flex-[1_1_0] overflow-hidden text-ellipsis whitespace-nowrap';

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
        className: joinClasses(
          CHAT_HISTORY_LINK_CLASSES,
          isActive
            ? CHAT_HISTORY_LINK_ACTIVE_CLASSES
            : CHAT_HISTORY_LINK_IDLE_CLASSES,
        ),
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
    <Button
      variant="text"
      size="sm"
      trailingIcon={showAllChats ? 'expand_less' : 'expand_more'}
      layoutClassName="justify-self-start"
      onClick={onToggle}
    >
      {showAllChats ? 'Show less' : 'Show more'}
    </Button>
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

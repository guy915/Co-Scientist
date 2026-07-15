import {type RefObject} from 'react';
import {Link} from 'react-router-dom';
import {type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {type SettingsSection} from './components/settings_dialog';
import {TruncatedLabel} from './components/truncated_label';
import {type ShellPanel} from './layout_hooks';
import {NAV_ICON_CLASSES, ShellPopover} from './layout_primitives';
import {tooltipClassNames} from './tooltip';

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

const SIDE_HEADING_CLASSES = 'ucs-side-heading';

const CHAT_LIST_CLASSES = 'ucs-chat-list';

const CHAT_HISTORY_LINK_CLASSES = 'ucs-chat-link';

const CHAT_HISTORY_LINK_ACTIVE_CLASSES = 'ucs-chat-link--active';

const CHAT_HISTORY_LABEL_CLASSES = 'ucs-chat-label';

const CHAT_HISTORY_MORE_CLASSES = 'ucs-chat-more';

// Per-region class bundles for the rail's expanded vs collapsed presentation,
// keyed by the single `navOpen` flag (see NavRail below). Replaces what would
// otherwise be six parallel `navOpen ? ... : ...` ternaries with one lookup.
const NAV_RAIL_VARIANTS = {
  open: {
    panel: NAV_PANEL_OPEN_CLASSES,
    group: NAV_GROUP_OPEN_CLASSES,
    items: NAV_ITEMS_OPEN_CLASSES,
    bottom: NAV_BOTTOM_CLASSES,
    item: NAV_ITEM_OPEN_CLASSES,
    label: NAV_LABEL_OPEN_CLASSES,
  },
  collapsed: {
    panel: NAV_PANEL_COLLAPSED_CLASSES,
    group: NAV_GROUP_COLLAPSED_CLASSES,
    items: NAV_ITEMS_COLLAPSED_CLASSES,
    bottom: NAV_BOTTOM_COLLAPSED_CLASSES,
    item: NAV_ITEM_COLLAPSED_CLASSES,
    label: NAV_LABEL_COLLAPSED_CLASSES,
  },
} as const;

/**
 * Renders the icon rail: Menu toggle, New chat, the chat-history sidebar,
 * and the bottom Settings control. All open/collapsed presentation is
 * derived here (and in the sub-components below) from the single `navOpen`
 * flag.
 *
 * @param navOpen Whether the rail is expanded (desktop) or open (mobile).
 * @param toggleNav Toggles the rail/drawer.
 * @param startNewChat Resets the chat workspace and navigates home.
 * @param history The recent runs to list in the Chats section.
 * @param activeRunId The run id to highlight as active, if any.
 * @param showAllChats Whether the chat list is expanded past its cap.
 * @param onToggleShowAllChats Toggles the chat-list expansion.
 * @param activePanel The currently open popover, if any.
 * @param onTogglePanel Opens/closes the given popover.
 * @param onOpenSettings Opens the full-screen Settings dialog at a section.
 * @param settingsControlRef Anchor ref for outside-click dismissal of the
 *   Settings popover.
 */
export function NavRail({
  navOpen,
  toggleNav,
  startNewChat,
  history,
  activeRunId,
  showAllChats,
  onToggleShowAllChats,
  activePanel,
  onTogglePanel,
  onOpenSettings,
  settingsControlRef,
}: {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  history: Run[];
  activeRunId: string | undefined;
  showAllChats: boolean;
  onToggleShowAllChats: () => void;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  onOpenSettings: (section: SettingsSection) => void;
  settingsControlRef: RefObject<HTMLDivElement | null>;
}) {
  const nav = navOpen ? NAV_RAIL_VARIANTS.open : NAV_RAIL_VARIANTS.collapsed;

  return (
    <aside className={nav.panel} aria-label="Primary navigation">
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
          <NavActionButton
            label="New chat"
            icon="edit_square"
            className={nav.item}
            labelClassName={nav.label}
            onClick={startNewChat}
          />
        </nav>
        <ChatHistorySidebar
          navOpen={navOpen}
          history={history}
          activeRunId={activeRunId}
          showAllChats={showAllChats}
          onToggleShowAllChats={onToggleShowAllChats}
        />
      </div>
      <div className={nav.bottom}>
        <RailSettingsControl
          navOpen={navOpen}
          activePanel={activePanel}
          onTogglePanel={onTogglePanel}
          onOpenSettings={onOpenSettings}
          settingsControlRef={settingsControlRef}
        />
      </div>
    </aside>
  );
}

// One row in the "Chats" list: the run's generated session title (falling
// back to a concise clause of the goal) linked to its details tab, with a
// tooltip showing the full research goal and the active run highlighted.
function ChatHistoryLink({run, isActive}: {run: Run; isActive: boolean}) {
  return (
    <Link
      to={`/runs/${run.id}/details`}
      className={tooltipClassNames({
        className: isActive
          ? `${CHAT_HISTORY_LINK_CLASSES} ${CHAT_HISTORY_LINK_ACTIVE_CLASSES}`
          : CHAT_HISTORY_LINK_CLASSES,
        placement: 'right',
        wrap: true,
      })}
      aria-current={isActive ? 'page' : undefined}
      data-tooltip={run.research_goal}
    >
      <TruncatedLabel
        className={CHAT_HISTORY_LABEL_CLASSES}
        text={run.title?.trim() || conciseTitle(run.research_goal)}
      />
    </Link>
  );
}

// The "Chats" section of the rail: the recent-run list (capped to 10 until
// expanded) with the active run highlighted.
function ChatHistorySidebar({
  navOpen,
  history,
  activeRunId,
  showAllChats,
  onToggleShowAllChats,
}: {
  navOpen: boolean;
  history: Run[];
  activeRunId: string | undefined;
  showAllChats: boolean;
  onToggleShowAllChats: () => void;
}) {
  const sideContentClasses = [
    SIDE_CONTENT_CLASSES,
    navOpen ? SIDE_CONTENT_OPEN_CLASSES : SIDE_CONTENT_COLLAPSED_CLASSES,
  ].join(' ');
  const visibleHistory = showAllChats ? history : history.slice(0, 10);
  const hasExtraChats = history.length > 10;

  return (
    <div className={sideContentClasses}>
      <p className={SIDE_HEADING_CLASSES}>Chats</p>
      <div className={CHAT_LIST_CLASSES}>
        {visibleHistory.map(run => (
          <ChatHistoryLink
            key={run.id}
            run={run}
            isActive={run.id === activeRunId}
          />
        ))}
        {hasExtraChats && (
          <button
            type="button"
            className={CHAT_HISTORY_MORE_CLASSES}
            onClick={onToggleShowAllChats}
          >
            {showAllChats ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>
    </div>
  );
}

// [label, icon, section] for each row of the Settings popover menu, in
// display order.
const SETTINGS_MENU_ITEMS: readonly [
  label: string,
  icon: IconName,
  section: SettingsSection,
][] = [
  ['Appearance', 'palette', 'appearance'],
  ['Model', 'neurology', 'model'],
  ['Help', 'help', 'help'],
];

// The Settings popover menu itself (Appearance/Model/Help), shown while the
// rail's Settings control is the active panel.
function SettingsPopoverMenu({
  onOpenSettings,
}: {
  onOpenSettings: (section: SettingsSection) => void;
}) {
  return (
    <ShellPopover className={`${RAIL_POPOVER_CLASSES} ucs-popover--menu`}>
      <div className={SETTINGS_MENU_CLASSES} role="menu">
        {SETTINGS_MENU_ITEMS.map(([label, icon, section]) => (
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
// its popover menu (Appearance/Model/Help).
function RailSettingsControl({
  navOpen,
  activePanel,
  onTogglePanel,
  onOpenSettings,
  settingsControlRef,
}: {
  navOpen: boolean;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  onOpenSettings: (section: SettingsSection) => void;
  settingsControlRef: RefObject<HTMLDivElement | null>;
}) {
  const nav = navOpen ? NAV_RAIL_VARIANTS.open : NAV_RAIL_VARIANTS.collapsed;

  return (
    <div
      ref={settingsControlRef}
      className={`${SETTINGS_CONTROL_CLASSES} ${
        navOpen
          ? 'ucs-settings-control--open'
          : 'ucs-settings-control--collapsed'
      }`}
    >
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

// A single rail action (Menu/hamburger, New chat): an icon plus a label that
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

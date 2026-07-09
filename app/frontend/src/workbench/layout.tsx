import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type RefObject,
  type SetStateAction,
} from 'react';
import {
  Link,
  useLocation,
  useNavigate,
  type NavigateFunction,
} from 'react-router-dom';
import {loadRunHistory, type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {
  SettingsDialog,
  type SettingsSection,
} from './components/settings_dialog';
import {TruncatedLabel} from './components/truncated_label';
import {DiagnosticsControl} from './layout_diagnostics';
import {isMobileViewport} from './hooks/use_is_mobile';
import {tooltipClassNames} from './tooltip';

// Which header popover is open. Only one of the two can be open at a time
// (see togglePanel below), and either is dismissed by an outside click,
// Escape, or navigation.
type ShellPanel = 'settings' | 'logs';

// The constants below pair a CSS class for the "open" shell state with one
// for the "collapsed"/default state; each pair is selected at render time by
// a single boolean (navOpen, or the active-route checks further down). The
// actual responsive behavior (desktop icon rail vs mobile off-canvas drawer,
// iOS-safe viewport sizing) lives in shell_surface.css, keyed off the
// `nav-open` / `nav-collapsed` shell classes and the ~700px breakpoint.
const WORKSPACE_CLASSES = 'ucs-workspace';

const WORKSPACE_RESPONSIVE_CLASSES = 'ucs-workspace--rounded-bottom';

const REPORT_WORKSPACE_CLASSES = 'ucs-workspace ucs-workspace--report';

const PAGE_CLASSES = 'ucs-page';

const HOME_PAGE_CLASSES = 'ucs-page ucs-page--home';

const REPORT_PAGE_CLASSES = 'ucs-page ucs-page--report';

const SHELL_OPEN_GRID_CLASSES = 'nav-open';

const SHELL_COLLAPSED_GRID_CLASSES = 'nav-collapsed';

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

const NAV_ICON_CLASSES = 'ucs-nav-icon';

const NAV_LABEL_OPEN_CLASSES = 'nav-label nav-label--open';

const NAV_LABEL_COLLAPSED_CLASSES = 'nav-label nav-label--collapsed';

const HEADER_CLASSES = 'ucs-header-action-bar';

const PRODUCT_LOCKUP_CLASSES = 'ucs-product-lockup';

const HEADER_TITLE_CLASSES = 'ucs-header-title';

const HEADER_ACTIONS_CLASSES = 'ucs-header-actions';

const SHELL_POPOVER_CLASSES = 'ucs-popover';

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

// The <main> class variant for a route: report layout on run routes, the
// home variant on '/', and the plain page otherwise.
function pageClassesFor(pathname: string, isRunRoute: boolean): string {
  if (isRunRoute) return REPORT_PAGE_CLASSES;
  return pathname === '/' ? HOME_PAGE_CLASSES : PAGE_CLASSES;
}

// Derives the route-dependent shell presentation: which workspace/page class
// variant to render and the sidebar/title keys that follow the active run.
// Isolated from Layout so the component itself stays a thin render/wiring
// function; see Layout's shellClass for the remaining (navOpen-dependent)
// piece, which stays inline since it is just two ternaries.
function deriveRoutePresentation(pathname: string): {
  isRunRoute: boolean;
  activeRunId: string | undefined;
  titleContextKey: string;
  workspaceClasses: string;
  pageClasses: string;
} {
  const isRunRoute = pathname.startsWith('/runs/');
  // The run id embedded in /runs/:id[/:tab], used to persistently highlight the
  // active conversation in the sidebar chat list.
  const activeRunId = isRunRoute ? pathname.split('/')[2] : undefined;
  // Clear the shell title only when the title-owning context changes: the run
  // id for run routes, else the pathname. Switching tabs within one run keeps
  // the same id, so the run's dispatched title survives (RunDetail stays
  // mounted across tabs and does not re-dispatch on a tab change).
  const titleContextKey = isRunRoute ? `run:${activeRunId}` : pathname;
  const workspaceClasses = isRunRoute
    ? REPORT_WORKSPACE_CLASSES
    : `${WORKSPACE_CLASSES} ${WORKSPACE_RESPONSIVE_CLASSES}`;

  return {
    isRunRoute,
    activeRunId,
    titleContextKey,
    workspaceClasses,
    pageClasses: pageClassesFor(pathname, isRunRoute),
  };
}

// The shell root's classes: the report/home variant (route-driven, see
// deriveRoutePresentation above) and the open/collapsed grid (navOpen-driven,
// see useLayoutChrome below). `nav-open`/`nav-collapsed` is the class
// shell_surface.css keys its responsive rules off: on desktop (>700px) it
// toggles the rail's grid column width; on mobile (<=700px) both variants
// collapse to a single full-width column and the rail instead becomes a
// fixed, off-canvas drawer that slides over the content (see the scrim below
// and the ~700px breakpoint in shell_surface.css for the iOS-safe dvh
// sizing).
function shellClassFor(isRunRoute: boolean, navOpen: boolean): string {
  return [
    'ucs-app-shell',
    isRunRoute ? 'report-shell' : 'home-shell',
    navOpen ? SHELL_OPEN_GRID_CLASSES : SHELL_COLLAPSED_GRID_CLASSES,
  ].join(' ');
}

// Builds the "New chat" / product-lockup handler: resets the chat workspace
// and dismisses the mobile drawer. On desktop the expanded rail is a user
// preference, so clicking Home or New chat leaves it untouched there.
function createStartNewChatHandler(
  navigate: NavigateFunction,
  setNavOpen: (open: boolean) => void,
): () => void {
  return () => {
    if (isMobileViewport()) setNavOpen(false);
    // Lets the chat workspace page (mounted separately) know to reset its own
    // session state; see ChatWorkspace's listener for 'cosci-new-chat'.
    window.dispatchEvent(new Event('cosci-new-chat'));
    void navigate('/', {state: {cosciAction: 'new-chat'}});
  };
}

/**
 * Renders the app shell with header navigation, main content, and footer.
 *
 * @param props The page content to render inside the layout.
 */
export function Layout({children}: {children: ReactNode}) {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    isRunRoute,
    activeRunId,
    titleContextKey,
    workspaceClasses,
    pageClasses,
  } = deriveRoutePresentation(location.pathname);
  const headerTitle = useHeaderTitle(titleContextKey);
  const {history, showAllChats, toggleShowAllChats} = useChatHistory(
    location.pathname,
  );
  const {
    navOpen,
    setNavOpen,
    activePanel,
    settingsSection,
    setSettingsSection,
    settingsControlRef,
    logsControlRef,
    toggleNav,
    togglePanel,
    openSettings,
  } = useLayoutChrome(location.pathname);
  const shellClass = shellClassFor(isRunRoute, navOpen);
  const startNewChat = createStartNewChatHandler(navigate, setNavOpen);

  return (
    <div className={shellClass}>
      <NavRail
        navOpen={navOpen}
        toggleNav={toggleNav}
        startNewChat={startNewChat}
        history={history}
        activeRunId={activeRunId}
        showAllChats={showAllChats}
        onToggleShowAllChats={toggleShowAllChats}
        activePanel={activePanel}
        onTogglePanel={togglePanel}
        onOpenSettings={openSettings}
        settingsControlRef={settingsControlRef}
      />
      <DrawerScrim navOpen={navOpen} onDismiss={() => setNavOpen(false)} />
      <section className={workspaceClasses}>
        <ShellHeader
          navOpen={navOpen}
          toggleNav={toggleNav}
          startNewChat={startNewChat}
          headerTitle={headerTitle}
          activePanel={activePanel}
          onTogglePanel={togglePanel}
          logsControlRef={logsControlRef}
        />
        <main className={pageClasses}>{children}</main>
      </section>
      {settingsSection && (
        <SettingsDialog
          section={settingsSection}
          onSectionChange={setSettingsSection}
          onClose={() => setSettingsSection(null)}
        />
      )}
    </div>
  );
}

// Sidebar chat history: the recent-run list state, kept as local state
// (rather than derived from a hook) so it can be refreshed imperatively from
// multiple triggers, plus the "show more" expansion flag. `pathname` drives
// the reload-on-navigation effect below.
function useChatHistory(pathname: string) {
  const [history, setHistory] = useState<Run[]>([]);
  // Sidebar chat list is capped to the 10 most recent entries until expanded.
  const [showAllChats, setShowAllChats] = useState(false);

  // Stable identity via useCallback (no deps) so it can safely be both an
  // effect dependency and an event listener reference below.
  const loadHistory = useCallback(async () => {
    setHistory(await loadRunHistory());
  }, []);

  // Reload the sidebar history on mount, whenever a run is created/started
  // (cosci-runs-changed), and on every navigation so status changes (e.g. a
  // run finishing) are reflected without a full page reload.
  useEffect(() => {
    void loadHistory();
    window.addEventListener('cosci-runs-changed', loadHistory);
    return () => {
      window.removeEventListener('cosci-runs-changed', loadHistory);
    };
  }, [loadHistory, pathname]);

  return {
    history,
    showAllChats,
    toggleShowAllChats: () => setShowAllChats(current => !current),
  };
}

// The header title override dispatched by page components (e.g. RunDetail)
// via the `cosci-header-title` CustomEvent, since the header lives in this
// shell above the routed page content. `contextKey` identifies the
// title-owning route (see Layout's titleContextKey) and clears any stale
// title when it changes.
function useHeaderTitle(contextKey: string): string {
  // Empty string means "no override" for the current route.
  const [overrideTitle, setOverrideTitle] = useState('');

  useEffect(() => {
    setOverrideTitle('');
  }, [contextKey]);

  // Registered once for the shell's lifetime (no deps) and torn down on
  // unmount.
  useEffect(() => {
    function onHeaderTitle(event: Event) {
      const custom = event as CustomEvent<string>;
      setOverrideTitle(custom.detail || '');
    }
    window.addEventListener('cosci-header-title', onHeaderTitle);
    return () => {
      window.removeEventListener('cosci-header-title', onHeaderTitle);
    };
  }, []);

  return overrideTitle;
}

// Close any open popover on navigation, and dismiss the mobile drawer so a
// chat tap doesn't leave the overlay covering the run it just opened. On the
// desktop rail the open/collapsed state is a user preference, so it is left
// untouched.
function useDismissChromeOnNavigate(
  pathname: string,
  setActivePanel: (panel: ShellPanel | null) => void,
  setNavOpen: (open: boolean) => void,
) {
  useEffect(() => {
    setActivePanel(null);
    if (isMobileViewport()) setNavOpen(false);
  }, [pathname]);
}

// Escape closes the mobile drawer (a standard dismiss affordance for an
// overlay); the desktop rail is unaffected.
function useEscapeClosesDrawer(
  navOpen: boolean,
  setNavOpen: (open: boolean) => void,
) {
  useEffect(() => {
    if (!navOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && isMobileViewport()) setNavOpen(false);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [navOpen]);
}

// Closes `activePanel` on a pointerdown landing outside both the Settings and
// Logs control anchors. Only attaches the listener while a popover is
// actually open (skipped via the early return otherwise), and detaches it on
// close/unmount so idle renders of the shell don't pay for a document-wide
// pointerdown listener. `activePanel` is a dep both to gate the effect and
// because the handler closure reads the two refs directly (stable across
// renders, so they don't need to be deps themselves).
function useDismissPanelOnOutsideClick(
  activePanel: ShellPanel | null,
  setActivePanel: (panel: ShellPanel | null) => void,
  settingsControlRef: RefObject<HTMLDivElement | null>,
  logsControlRef: RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    if (!activePanel) return;
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      const settingsContains = settingsControlRef.current?.contains(target);
      const logsContains = logsControlRef.current?.contains(target);
      if (!settingsContains && !logsContains) setActivePanel(null);
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [activePanel]);
}

// The rail/popover action handlers, derived from the three chrome setters:
// toggling the nav rail, toggling a popover open/closed, and opening the
// full-screen Settings dialog for a given section.
function useChromeActions(
  setNavOpen: Dispatch<SetStateAction<boolean>>,
  setActivePanel: Dispatch<SetStateAction<ShellPanel | null>>,
  setSettingsSection: Dispatch<SetStateAction<SettingsSection | null>>,
) {
  // Flips the rail between expanded/collapsed (desktop) or open/closed
  // (mobile drawer), and closes any open popover since its anchor may move.
  function toggleNav() {
    setNavOpen(open => !open);
    setActivePanel(null);
  }

  // Opens `panel`, or closes it if it's already the active one (so the same
  // trigger button acts as both opener and toggle-closer).
  function togglePanel(panel: ShellPanel) {
    setActivePanel(current => (current === panel ? null : panel));
  }

  function openSettings(section: SettingsSection) {
    setActivePanel(null);
    // The dialog overlays the content; drop the mobile drawer beneath it so
    // dismissing the dialog doesn't land back on a stale overlay.
    if (isMobileViewport()) setNavOpen(false);
    setSettingsSection(section);
  }

  return {toggleNav, togglePanel, openSettings};
}

// Bundles the rail's open/collapsed state, the mutually-exclusive
// Settings/Logs popover, and the full-screen Settings dialog, plus (via the
// sub-hooks above) the actions and effects that keep them in sync with
// navigation, Escape, and outside clicks.
function useLayoutChrome(pathname: string) {
  // Collapsed icon rail by default, matching the reference product; the
  // hamburger expands it. On mobile this same flag toggles an off-canvas
  // drawer instead (see shell_surface.css's <=700px breakpoint).
  const [navOpen, setNavOpen] = useState(false);
  // Which header popover (Settings menu or the Logs panel) is currently
  // shown, if any; the two are mutually exclusive via togglePanel.
  const [activePanel, setActivePanel] = useState<ShellPanel | null>(null);
  // Non-null renders the full-screen SettingsDialog overlay for that section.
  const [settingsSection, setSettingsSection] =
    useState<SettingsSection | null>(null);
  // Anchors for the outside-pointerdown handler below: a click landing
  // outside both refs closes whichever popover is open.
  const settingsControlRef = useRef<HTMLDivElement>(null);
  const logsControlRef = useRef<HTMLDivElement>(null);

  const {toggleNav, togglePanel, openSettings} = useChromeActions(
    setNavOpen,
    setActivePanel,
    setSettingsSection,
  );

  useDismissChromeOnNavigate(pathname, setActivePanel, setNavOpen);
  useEscapeClosesDrawer(navOpen, setNavOpen);
  useDismissPanelOnOutsideClick(
    activePanel,
    setActivePanel,
    settingsControlRef,
    logsControlRef,
  );

  return {
    navOpen,
    setNavOpen,
    activePanel,
    settingsSection,
    setSettingsSection,
    settingsControlRef,
    logsControlRef,
    toggleNav,
    togglePanel,
    openSettings,
  };
}

// Backdrop behind the off-canvas drawer on mobile; only rendered while the
// drawer is open, and a tap on it dismisses it. On desktop the rail never
// overlaps content, so this has no visible effect there.
function DrawerScrim({
  navOpen,
  onDismiss,
}: {
  navOpen: boolean;
  onDismiss: () => void;
}) {
  if (!navOpen) return null;
  return <div className="ucs-scrim" aria-hidden="true" onClick={onDismiss} />;
}

// Mobile drawer / desktop rail toggle; the header's leftmost control.
function HamburgerButton({
  navOpen,
  onClick,
}: {
  navOpen: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="ucs-nav-hamburger"
      aria-label="Open navigation"
      aria-expanded={navOpen}
      aria-controls="primary-navigation"
      onClick={onClick}
    >
      <Icon aria-hidden="true" className={NAV_ICON_CLASSES} name="menu" />
    </button>
  );
}

// The Co-Scientist wordmark/icon; doubles as a "go home" / new-chat control.
function ProductLockup({onClick}: {onClick: () => void}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: PRODUCT_LOCKUP_CLASSES,
        placement: 'right',
      })}
      aria-label="Go to Co-Scientist home"
      data-tooltip="Home"
      onClick={onClick}
    >
      <GoogleLabsIcon aria-hidden="true" />
      <span>Co-Scientist</span>
    </button>
  );
}

// The header action bar: hamburger (mobile drawer / desktop rail toggle),
// product lockup (doubles as "go home"), the page's dispatched title, and
// the Logs/diagnostics control.
function ShellHeader({
  navOpen,
  toggleNav,
  startNewChat,
  headerTitle,
  activePanel,
  onTogglePanel,
  logsControlRef,
}: {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  headerTitle: string;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  logsControlRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <header className={HEADER_CLASSES}>
      <HamburgerButton navOpen={navOpen} onClick={toggleNav} />
      <ProductLockup onClick={startNewChat} />
      <div className={HEADER_TITLE_CLASSES}>
        {headerTitle && (
          <TruncatedLabel
            className="block min-w-0 overflow-hidden whitespace-nowrap"
            text={headerTitle}
          />
        )}
      </div>
      <div ref={logsControlRef} className={HEADER_ACTIONS_CLASSES}>
        <DiagnosticsControl
          open={activePanel === 'logs'}
          onToggle={() => onTogglePanel('logs')}
          renderPopover={(children, className) => (
            <ShellPopover className={className}>{children}</ShellPopover>
          )}
        />
      </div>
    </header>
  );
}

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

// The icon rail: Menu toggle, New chat, the chat-history sidebar, and the
// bottom Settings control. All open/collapsed presentation is derived here
// (and in the sub-components below) from the single `navOpen` flag.
function NavRail({
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

// One row in the "Chats" list: the run's title linked to its details tab,
// with a tooltip showing the full research goal and the active run
// highlighted.
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
        text={conciseTitle(run.research_goal)}
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

// Shared popover shell for both the Settings menu and the Logs panel; the
// caller supplies extra positioning/sizing classes via `className`.
function ShellPopover({
  children,
  className,
}: {
  children: ReactNode;
  className: string;
}) {
  return (
    <div className={`${SHELL_POPOVER_CLASSES} ${className}`} role="status">
      {children}
    </div>
  );
}

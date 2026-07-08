import {useCallback, useEffect, useRef, useState, type ReactNode} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
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

/**
 * Renders the app shell with header navigation, main content, and footer.
 *
 * @param props The page content to render inside the layout.
 */
export function Layout({children}: {children: ReactNode}) {
  const navigate = useNavigate();
  const location = useLocation();
  // Title shown in the header bar; pages opt in by dispatching the
  // `cosci-header-title` CustomEvent (see the listener effect below). Empty
  // string means "no override" for the current route.
  const [overrideTitle, setOverrideTitle] = useState('');
  // Sidebar chat history; kept as local state (rather than derived from a
  // hook) so it can be refreshed imperatively from multiple triggers below.
  const [history, setHistory] = useState<Run[]>([]);
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
  // Sidebar chat list is capped to the 10 most recent entries until expanded.
  const [showAllChats, setShowAllChats] = useState(false);
  // Anchors for the outside-pointerdown handler below: a click landing
  // outside both refs closes whichever popover is open.
  const settingsControlRef = useRef<HTMLDivElement>(null);
  const logsControlRef = useRef<HTMLDivElement>(null);
  const isRunRoute = location.pathname.startsWith('/runs/');
  // The run id embedded in /runs/:id[/:tab], used to persistently highlight the
  // active conversation in the sidebar chat list.
  const activeRunId = isRunRoute ? location.pathname.split('/')[2] : undefined;
  const headerTitle = overrideTitle || '';
  const visibleHistory = showAllChats ? history : history.slice(0, 10);
  const hasExtraChats = history.length > 10;
  const sideContentClasses = [
    SIDE_CONTENT_CLASSES,
    navOpen ? SIDE_CONTENT_OPEN_CLASSES : SIDE_CONTENT_COLLAPSED_CLASSES,
  ].join(' ');
  const workspaceClasses = isRunRoute
    ? REPORT_WORKSPACE_CLASSES
    : `${WORKSPACE_CLASSES} ${WORKSPACE_RESPONSIVE_CLASSES}`;
  const isHomeRoute = location.pathname === '/';
  const pageClasses = isRunRoute
    ? REPORT_PAGE_CLASSES
    : isHomeRoute
      ? HOME_PAGE_CLASSES
      : PAGE_CLASSES;
  // `nav-open`/`nav-collapsed` is the class shell_surface.css keys its
  // responsive rules off: on desktop (>700px) it toggles the rail's grid
  // column width; on mobile (<=700px) both variants collapse to a single
  // full-width column and the rail instead becomes a fixed, off-canvas
  // drawer that slides over the content (see the scrim below and the
  // ~700px breakpoint in shell_surface.css for the iOS-safe dvh sizing).
  const shellClass = [
    'ucs-app-shell',
    isRunRoute ? 'report-shell' : 'home-shell',
    navOpen ? SHELL_OPEN_GRID_CLASSES : SHELL_COLLAPSED_GRID_CLASSES,
  ].join(' ');
  // The remaining nav* variants below all key off the same navOpen flag to
  // swap each rail sub-region between its expanded (label + icon) and
  // collapsed (icon-only) presentation.
  const navPanelClasses = navOpen
    ? NAV_PANEL_OPEN_CLASSES
    : NAV_PANEL_COLLAPSED_CLASSES;
  const navGroupClasses = navOpen
    ? NAV_GROUP_OPEN_CLASSES
    : NAV_GROUP_COLLAPSED_CLASSES;
  const navItemsClasses = navOpen
    ? NAV_ITEMS_OPEN_CLASSES
    : NAV_ITEMS_COLLAPSED_CLASSES;
  const navBottomClasses = navOpen
    ? NAV_BOTTOM_CLASSES
    : NAV_BOTTOM_COLLAPSED_CLASSES;
  const navItemClasses = navOpen
    ? NAV_ITEM_OPEN_CLASSES
    : NAV_ITEM_COLLAPSED_CLASSES;
  const navLabelClasses = navOpen
    ? NAV_LABEL_OPEN_CLASSES
    : NAV_LABEL_COLLAPSED_CLASSES;

  function startNewChat() {
    // Only dismiss the mobile drawer; on desktop the expanded rail is a user
    // preference and clicking Home or New chat should leave it untouched.
    if (isMobileViewport()) setNavOpen(false);
    // Lets the chat workspace page (mounted separately) know to reset its own
    // session state; see ChatWorkspace's listener for 'cosci-new-chat'.
    window.dispatchEvent(new Event('cosci-new-chat'));
    void navigate('/', {state: {cosciAction: 'new-chat'}});
  }

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

  // Close any open popover on navigation, and dismiss the mobile drawer so a
  // chat tap doesn't leave the overlay covering the run it just opened. On the
  // desktop rail the open/collapsed state is a user preference, so it is left
  // untouched.
  useEffect(() => {
    setActivePanel(null);
    if (isMobileViewport()) setNavOpen(false);
  }, [location.pathname]);

  // Escape closes the mobile drawer (a standard dismiss affordance for an
  // overlay); the desktop rail is unaffected.
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

  // Clear the shell title only when the title-owning context changes: the run
  // id for run routes, else the pathname. Switching tabs within one run keeps
  // the same id, so the run's dispatched title survives (RunDetail stays
  // mounted across tabs and does not re-dispatch on a tab change).
  const titleContextKey = isRunRoute ? `run:${activeRunId}` : location.pathname;
  useEffect(() => {
    setOverrideTitle('');
  }, [titleContextKey]);

  // Only attaches the listener while a popover is actually open (skipped
  // via the early return otherwise), and detaches it on close/unmount so
  // idle renders of the shell don't pay for a document-wide pointerdown
  // listener. `activePanel` is a dep both to gate the effect and because the
  // handler closure reads settingsControlRef/logsControlRef via refs (stable
  // across renders, so they don't need to be deps themselves).
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

  // Page components (e.g. RunDetail) set the header title by dispatching a
  // `cosci-header-title` CustomEvent<string> rather than via props, since the
  // header lives in this shell above the routed page content. Registered
  // once for the shell's lifetime (no deps) and torn down on unmount.
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
  }, [loadHistory, location.pathname]);

  return (
    <div className={shellClass}>
      <aside className={navPanelClasses} aria-label="Primary navigation">
        <div className={navGroupClasses}>
          <NavActionButton
            label="Menu"
            icon="menu"
            className={navItemClasses}
            labelClassName={navLabelClasses}
            expanded={navOpen}
            controls="primary-navigation"
            onClick={toggleNav}
          />
          <nav id="primary-navigation" className={navItemsClasses}>
            <NavActionButton
              label="New chat"
              icon="edit_square"
              className={navItemClasses}
              labelClassName={navLabelClasses}
              onClick={startNewChat}
            />
          </nav>
          <div className={sideContentClasses}>
            <p className={SIDE_HEADING_CLASSES}>Chats</p>
            <div className={CHAT_LIST_CLASSES}>
              {visibleHistory.map(run => {
                const isActive = run.id === activeRunId;
                return (
                  <Link
                    key={run.id}
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
              })}
              {hasExtraChats && (
                <button
                  type="button"
                  className={CHAT_HISTORY_MORE_CLASSES}
                  onClick={() => setShowAllChats(current => !current)}
                >
                  {showAllChats ? 'Show less' : 'Show more'}
                </button>
              )}
            </div>
          </div>
        </div>
        <div className={navBottomClasses}>
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
              className={navItemClasses}
              labelClassName={navLabelClasses}
              expanded={activePanel === 'settings'}
              onClick={() => togglePanel('settings')}
            />
            {activePanel === 'settings' && (
              <ShellPopover
                className={`${RAIL_POPOVER_CLASSES} ucs-popover--menu`}
              >
                <div className={SETTINGS_MENU_CLASSES} role="menu">
                  <SettingsMenuButton
                    label="Appearance"
                    icon="palette"
                    onClick={() => openSettings('appearance')}
                  />
                  <SettingsMenuButton
                    label="Model"
                    icon="neurology"
                    onClick={() => openSettings('model')}
                  />
                  <SettingsMenuButton
                    label="Help"
                    icon="help"
                    onClick={() => openSettings('help')}
                  />
                </div>
              </ShellPopover>
            )}
          </div>
        </div>
      </aside>
      {/* Backdrop behind the off-canvas drawer on mobile; only rendered while
          the drawer is open, and a tap on it dismisses it. On desktop the
          rail never overlaps content, so this has no visible effect there. */}
      {navOpen && (
        <div
          className="ucs-scrim"
          aria-hidden="true"
          onClick={() => setNavOpen(false)}
        />
      )}
      <section className={workspaceClasses}>
        <header className={HEADER_CLASSES}>
          <button
            type="button"
            className="ucs-nav-hamburger"
            aria-label="Open navigation"
            aria-expanded={navOpen}
            aria-controls="primary-navigation"
            onClick={toggleNav}
          >
            <Icon aria-hidden="true" className={NAV_ICON_CLASSES} name="menu" />
          </button>
          <button
            type="button"
            className={tooltipClassNames({
              className: PRODUCT_LOCKUP_CLASSES,
              placement: 'right',
            })}
            aria-label="Go to Co-Scientist home"
            data-tooltip="Home"
            onClick={startNewChat}
          >
            <GoogleLabsIcon aria-hidden="true" />
            <span>Co-Scientist</span>
          </button>
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
              onToggle={() => togglePanel('logs')}
              renderPopover={(children, className) => (
                <ShellPopover className={className}>{children}</ShellPopover>
              )}
            />
          </div>
        </header>
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

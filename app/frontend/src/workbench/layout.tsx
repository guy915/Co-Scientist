import {useEffect, useRef, useState, type ReactNode} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {listDemoRuns, listRuns, type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {TruncatedLabel} from './components/truncated_label';
import {DiagnosticsControl} from './layout_diagnostics';
import {isMobileViewport} from './hooks/use_is_mobile';
import {useTheme} from './theme_context';
import {tooltipClassNames} from './tooltip';

type ShellPanel = 'settings' | 'logs';
type ThemeMode = 'system' | 'light' | 'dark';

const THEME_MODES: Array<{mode: ThemeMode; icon: IconName; label: string}> = [
  {mode: 'system', icon: 'computer', label: 'System'},
  {mode: 'light', icon: 'light_mode', label: 'Light'},
  {mode: 'dark', icon: 'dark_mode', label: 'Dark'},
];

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

const THEME_SEGMENT_CLASSES = 'ucs-theme-segment ucs-theme-segment--inline';

const THEME_BUTTON_BASE_CLASSES = 'ucs-theme-button';

const THEME_BUTTON_ACTIVE_CLASSES = 'selected';

const THEME_BUTTON_ICON_CLASSES = 'ucs-theme-button-icon';

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
  const {mode, setMode} = useTheme();
  const [overrideTitle, setOverrideTitle] = useState('');
  const [history, setHistory] = useState<Run[]>([]);
  // Collapsed icon rail by default, matching the reference product; the
  // hamburger expands it.
  const [navOpen, setNavOpen] = useState(false);
  const [activePanel, setActivePanel] = useState<ShellPanel | null>(null);
  const [showAllChats, setShowAllChats] = useState(false);
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
  const chatListClasses = CHAT_LIST_CLASSES;
  const workspaceClasses = isRunRoute
    ? REPORT_WORKSPACE_CLASSES
    : `${WORKSPACE_CLASSES} ${WORKSPACE_RESPONSIVE_CLASSES}`;
  const isHomeRoute = location.pathname === '/';
  const pageClasses = isRunRoute
    ? REPORT_PAGE_CLASSES
    : isHomeRoute
      ? HOME_PAGE_CLASSES
      : PAGE_CLASSES;
  const shellClass = [
    'ucs-app-shell',
    isRunRoute ? 'report-shell' : 'home-shell',
    navOpen ? SHELL_OPEN_GRID_CLASSES : SHELL_COLLAPSED_GRID_CLASSES,
  ].join(' ');
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
    window.dispatchEvent(new Event('cosci-new-chat'));
    void navigate('/', {state: {cosciAction: 'new-chat'}});
  }

  function toggleNav() {
    setNavOpen(open => !open);
    setActivePanel(null);
  }

  function togglePanel(panel: ShellPanel) {
    setActivePanel(current => (current === panel ? null : panel));
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

  useEffect(() => {
    let ignore = false;
    async function loadHistory() {
      const [ownedRuns, demoRuns] = await Promise.all([
        listRuns().catch(() => [] as Run[]),
        listDemoRuns().catch(() => [] as Run[]),
      ]);
      if (ignore) return;
      const byId = new Map<string, Run>();
      for (const item of [...ownedRuns, ...demoRuns]) byId.set(item.id, item);
      setHistory(
        [...byId.values()].sort((a, b) => b.updated_at - a.updated_at),
      );
    }
    void loadHistory();
    return () => {
      ignore = true;
    };
  }, []);

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
            <div className={chatListClasses}>
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
              <ShellPopover className={RAIL_POPOVER_CLASSES}>
                <div
                  className={THEME_SEGMENT_CLASSES}
                  role="group"
                  aria-label="Theme"
                >
                  {THEME_MODES.map(option => (
                    <ThemeModeButton
                      key={option.mode}
                      {...option}
                      active={mode === option.mode}
                      onModeChange={setMode}
                    />
                  ))}
                </div>
              </ShellPopover>
            )}
          </div>
        </div>
      </aside>
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
    </div>
  );
}

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

function ThemeModeButton({
  mode,
  active,
  icon,
  label,
  onModeChange,
}: {
  mode: 'system' | 'light' | 'dark';
  active: boolean;
  icon: IconName;
  label: string;
  onModeChange: (mode: ThemeMode) => void;
}) {
  return (
    <button
      type="button"
      className={
        active
          ? `${THEME_BUTTON_BASE_CLASSES} ${THEME_BUTTON_ACTIVE_CLASSES}`
          : THEME_BUTTON_BASE_CLASSES
      }
      aria-pressed={active}
      onClick={() => onModeChange(mode)}
    >
      <Icon
        aria-hidden="true"
        className={THEME_BUTTON_ICON_CLASSES}
        name={icon}
      />
      <span>{label}</span>
    </button>
  );
}

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

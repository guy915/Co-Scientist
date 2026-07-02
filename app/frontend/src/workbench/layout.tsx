import {useEffect, useRef, useState, type ReactNode} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {listDemoRuns, listRuns, type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {DiagnosticsControl} from './layout_diagnostics';
import {useTheme} from './theme_context';
import {tooltipClassNames} from './tooltip';

type ShellPanel = 'settings' | 'logs';
type ThemeMode = 'system' | 'light' | 'dark';

const THEME_MODES: Array<{mode: ThemeMode; icon: IconName; label: string}> = [
  {mode: 'system', icon: 'computer', label: 'System'},
  {mode: 'light', icon: 'light_mode', label: 'Light'},
  {mode: 'dark', icon: 'dark_mode', label: 'Dark'},
];

const WORKSPACE_CLASSES =
  'ucs-workspace grid min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden ' +
  'rounded-tl-[1.85rem] bg-[var(--cosci-workspace-bg)]';

const WORKSPACE_RESPONSIVE_CLASSES = 'rounded-bl-[1.9rem]';

const REPORT_WORKSPACE_CLASSES =
  'ucs-workspace min-h-screen !overflow-hidden rounded-bl-[1.9rem] ' +
  'max-[700px]:!min-w-0 max-[700px]:!overflow-hidden';

const PAGE_CLASSES =
  'ucs-page min-w-0 h-[calc(100vh-4.5rem)] overflow-auto p-0';

const HOME_PAGE_CLASSES =
  'ucs-page min-[1181px]:!h-[calc(100vh-4.5rem)] ' +
  'min-[1181px]:!overflow-hidden max-[1180px]:!overflow-y-auto ' +
  'max-[1180px]:!overflow-x-hidden';

const REPORT_PAGE_CLASSES =
  'ucs-page !h-[calc(100vh-4.5rem)] min-h-0 !overflow-hidden !p-0 ' +
  'max-[700px]:!min-w-0';

const SHELL_OPEN_GRID_CLASSES =
  'nav-open grid bg-[var(--cosci-rail)] min-[701px]:!grid-cols-[17.25rem_minmax(0,1fr)] ' +
  'max-[700px]:!grid-cols-[4.125rem_minmax(0,1fr)]';

const SHELL_COLLAPSED_GRID_CLASSES =
  'nav-collapsed grid bg-[var(--cosci-rail)] min-[701px]:!grid-cols-[4.75rem_minmax(0,1fr)] ' +
  'max-[700px]:!grid-cols-[4.125rem_minmax(0,1fr)]';

const NAV_PANEL_BASE_CLASSES =
  'ucs-nav-panel box-border flex h-screen w-full flex-col items-center ' +
  'justify-between border-r-0 bg-[var(--cosci-rail)] py-5 ' +
  'max-[700px]:!w-[4.125rem] max-[700px]:!min-w-[4.125rem] ' +
  'max-[700px]:!max-w-[4.125rem] max-[700px]:!items-center ' +
  'max-[700px]:!overflow-hidden max-[700px]:!px-0 max-[700px]:!py-4';

const NAV_PANEL_OPEN_CLASSES =
  `${NAV_PANEL_BASE_CLASSES} min-[701px]:!items-stretch min-[701px]:!px-3 ` +
  'min-[701px]:!py-4';

const NAV_PANEL_COLLAPSED_CLASSES =
  `${NAV_PANEL_BASE_CLASSES} min-[701px]:!items-center min-[701px]:!px-0 ` +
  'min-[701px]:!py-4';

const NAV_GROUP_OPEN_CLASSES =
  'ucs-nav-top grid max-[700px]:w-full max-[700px]:items-center ' +
  'max-[700px]:justify-items-center max-[700px]:gap-[0.65rem] ' +
  'min-[701px]:w-full min-[701px]:items-stretch min-[701px]:gap-1 ' +
  'min-[701px]:mt-1';

const NAV_GROUP_COLLAPSED_CLASSES =
  'ucs-nav-top grid w-full items-center justify-items-center gap-[0.74rem] ' +
  'mt-0 max-[700px]:gap-[0.65rem]';

const NAV_ITEMS_OPEN_CLASSES =
  'ucs-nav-items grid gap-[0.85rem] mt-[1.4rem] max-[700px]:w-full max-[700px]:items-center ' +
  'max-[700px]:justify-items-center max-[700px]:gap-[0.65rem] ' +
  'min-[701px]:!w-full min-[701px]:!items-stretch min-[701px]:!gap-1 ' +
  'min-[701px]:!mt-1';

const NAV_ITEMS_COLLAPSED_CLASSES =
  'ucs-nav-items grid !w-full !items-center !justify-items-center ' +
  '!gap-[0.74rem] !mt-[0.74rem] max-[700px]:!gap-[0.65rem]';

const NAV_BOTTOM_CLASSES =
  'ucs-nav-bottom relative grid items-center justify-items-center gap-[0.8rem] p-0 ' +
  'max-[700px]:w-full max-[700px]:items-center ' +
  'max-[700px]:justify-items-center max-[700px]:gap-[0.65rem]';

const NAV_BOTTOM_COLLAPSED_CLASSES =
  `${NAV_BOTTOM_CLASSES} min-[701px]:!w-full min-[701px]:!items-center ` +
  'min-[701px]:!justify-items-center min-[701px]:!gap-[0.74rem] ' +
  'min-[701px]:!mt-0';

const NAV_ITEM_OPEN_CLASSES =
  'ucs-nav-item grid size-10 min-h-10 cursor-pointer place-items-center ' +
  'rounded-full border-0 bg-transparent p-0 text-[var(--cosci-shell-icon)] ' +
  'no-underline hover:bg-[var(--cosci-shell-hover-bg)] ' +
  'hover:text-[var(--cosci-shell-hover-text)] ' +
  'focus-visible:bg-[var(--cosci-shell-hover-bg)] ' +
  'focus-visible:text-[var(--cosci-shell-hover-text)] max-[700px]:!grid ' +
  'max-[700px]:!size-10 ' +
  'max-[700px]:!min-h-10 max-[700px]:!min-w-10 max-[700px]:!grid-cols-[1fr] ' +
  'max-[700px]:!place-items-center max-[700px]:!overflow-hidden ' +
  'max-[700px]:!rounded-full max-[700px]:!p-0 min-[701px]:!grid ' +
  'min-[701px]:!h-[2.45rem] min-[701px]:!min-h-[2.45rem] ' +
  'min-[701px]:!w-full min-[701px]:!grid-cols-[1.5rem_minmax(0,1fr)] ' +
  'min-[701px]:!items-center min-[701px]:!justify-stretch ' +
  'min-[701px]:!justify-items-start min-[701px]:!gap-x-[0.72rem] ' +
  'min-[701px]:!rounded-full min-[701px]:!px-3 min-[701px]:!py-0 ' +
  'min-[701px]:!text-left min-[701px]:!leading-none';

const NAV_ITEM_COLLAPSED_CLASSES =
  'ucs-nav-item !grid !size-10 !min-h-10 !grid-cols-[1fr] !place-items-center ' +
  '!justify-self-center !rounded-full !border-0 !bg-transparent !p-0 ' +
  '!text-[var(--cosci-shell-icon)] hover:!bg-[var(--cosci-shell-hover-bg)] ' +
  'hover:!text-[var(--cosci-shell-hover-text)] ' +
  'focus-visible:!bg-[var(--cosci-shell-hover-bg)] ' +
  'focus-visible:!text-[var(--cosci-shell-hover-text)] max-[700px]:!min-w-10 ' +
  'max-[700px]:!overflow-hidden';

const NAV_ICON_CLASSES =
  'grid size-6 min-h-6 min-w-6 place-items-center justify-self-center ' +
  'text-xl leading-none';

const HIDDEN_ON_MOBILE_CLASSES =
  'max-[700px]:!hidden max-[700px]:!max-w-0 max-[700px]:!opacity-0 ' +
  'max-[700px]:!invisible';

const VISIBLE_ON_DESKTOP_CLASSES =
  'min-[701px]:!max-w-none min-[701px]:!opacity-100 min-[701px]:!visible';

const NAV_LABEL_OPEN_CLASSES =
  `nav-label ${HIDDEN_ON_MOBILE_CLASSES} min-[701px]:!block ` +
  VISIBLE_ON_DESKTOP_CLASSES;

const NAV_LABEL_COLLAPSED_CLASSES = `nav-label w-0 max-w-0 ${HIDDEN_ON_MOBILE_CLASSES}`;

const HEADER_CLASSES =
  'ucs-header-action-bar sticky top-0 z-20 flex min-h-[4.5rem] items-center ' +
  'justify-between gap-4 border-b-0 bg-[var(--cosci-surface-bg)] ' +
  'px-[1.625rem] max-[700px]:!min-w-0 ' +
  'max-[700px]:!px-[0.85rem]';

const PRODUCT_LOCKUP_CLASSES =
  'ucs-product-lockup inline-flex cursor-pointer items-center gap-2 ' +
  'text-[1.375rem] font-medium text-[var(--cosci-home-heading)] no-underline ' +
  '[&_svg]:size-[1.32rem] [&_svg]:flex-[0_0_1.32rem] ' +
  '[&_svg]:text-[var(--cosci-logo-color)] [&_svg_path]:fill-current ' +
  '[&_svg_path]:stroke-current max-[700px]:ml-[3.25rem]';

const HEADER_TITLE_CLASSES =
  'ucs-header-title absolute left-1/2 -translate-x-1/2 text-base font-medium ' +
  'text-[#202124] dark:text-[#e8eaed] max-[700px]:!hidden';

const HEADER_ACTIONS_CLASSES =
  'ucs-header-actions absolute top-1/2 right-[1.35rem] flex min-w-max ' +
  '-translate-y-1/2 items-center gap-[0.55rem] max-[700px]:!hidden';

const SHELL_POPOVER_CLASSES =
  'ucs-popover absolute z-[35] grid w-80 gap-[0.35rem] rounded-2xl border ' +
  'border-[#dadce0] bg-white p-3 text-[#202124] ' +
  'dark:border-[#3c4043] dark:bg-[#202124] dark:text-[#e8eaed]';

const RAIL_POPOVER_CLASSES =
  'ucs-popover--rail bottom-[0.15rem] left-12 !w-[min(18.25rem,calc(100vw-4rem))] !p-[0.8rem]';

const SETTINGS_CONTROL_CLASSES = 'ucs-settings-control relative grid';

const THEME_SEGMENT_CLASSES =
  'ucs-theme-segment ucs-theme-segment--inline m-[0.1rem_0_0.45rem] grid ' +
  'grid-cols-[repeat(3,minmax(0,1fr))] gap-[0.3rem] rounded-full border ' +
  'border-[#dadce0] bg-[#f8fafd] p-[0.18rem] dark:border-[#3c4043] ' +
  'dark:bg-[#171717]';

const THEME_BUTTON_BASE_CLASSES =
  'flex min-h-[2.2rem] min-w-0 cursor-pointer items-center justify-center ' +
  'gap-[0.28rem] rounded-full border-0 bg-transparent px-[0.44rem] ' +
  'font-[inherit] text-[0.74rem] font-semibold text-[#3c4043] ' +
  'dark:text-[#e8eaed]';

const THEME_BUTTON_ACTIVE_CLASSES =
  'selected bg-[#d3e3fd] text-[#0b57d0] dark:bg-[#0b57d0] dark:text-[#f8fbff]';

const THEME_BUTTON_ICON_CLASSES = 'text-base';

const SIDE_CONTENT_BASE_CLASSES =
  'gemini-side-content grid min-w-0 gap-[0.35rem] overflow-hidden opacity-100 visible';

const HOME_SIDE_CONTENT_CLASSES = `${SIDE_CONTENT_BASE_CLASSES} mt-[0.85rem] max-h-72`;

const REPORT_SIDE_CONTENT_CLASSES = `${SIDE_CONTENT_BASE_CLASSES} mt-6 max-h-80`;

const SIDE_CONTENT_OPEN_CLASSES =
  `${HIDDEN_ON_MOBILE_CLASSES} min-[701px]:!block ` +
  VISIBLE_ON_DESKTOP_CLASSES;

const SIDE_CONTENT_COLLAPSED_CLASSES =
  `${HIDDEN_ON_MOBILE_CLASSES} min-[701px]:!grid min-[701px]:!max-h-0 ` +
  'min-[701px]:!mt-0 min-[701px]:!opacity-0 min-[701px]:!invisible';

const SIDE_HEADING_CLASSES =
  'gemini-side-heading mt-4 mb-[0.4rem] text-[0.78rem] font-medium ' +
  'text-[#5f6368] dark:text-[var(--cosci-subtle)]';

const HOME_CHAT_LIST_CLASSES = 'gemini-chat-list grid min-w-0 gap-[0.35rem]';

const REPORT_CHAT_LIST_CLASSES = 'gemini-chat-list grid min-w-0 gap-[0.1rem]';

const CHAT_HISTORY_LINK_CLASSES =
  'relative flex min-h-[2.35rem] min-w-0 items-center overflow-visible ' +
  'rounded-full px-3 text-[0.86rem] leading-[2.35rem] text-[#3c4043] ' +
  'no-underline hover:bg-[#dfeafc] hover:text-[#202124] ' +
  'focus-visible:bg-[#dfeafc] focus-visible:text-[#202124] ' +
  'dark:text-[var(--cosci-muted)] dark:hover:bg-[#303134] ' +
  'dark:hover:text-[var(--cosci-text)] dark:focus-visible:bg-[#303134] ' +
  'dark:focus-visible:text-[var(--cosci-text)]';

const CHAT_HISTORY_LABEL_CLASSES =
  'min-w-0 overflow-hidden text-ellipsis whitespace-nowrap';

const CHAT_HISTORY_MORE_CLASSES =
  'justify-self-start rounded-full border-0 bg-transparent px-3 ' +
  'py-[0.48rem] font-[inherit] text-[0.84rem] text-[#3c4043] ' +
  'hover:bg-[#dfeafc] hover:text-[#202124] focus-visible:bg-[#dfeafc] ' +
  'focus-visible:text-[#202124] dark:text-[var(--cosci-muted)] ' +
  'dark:hover:bg-[#303134] dark:hover:text-[var(--cosci-text)] ' +
  'dark:focus-visible:bg-[#303134] dark:focus-visible:text-[var(--cosci-text)]';

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
  const [navOpen, setNavOpen] = useState(true);
  const [activePanel, setActivePanel] = useState<ShellPanel | null>(null);
  const [showAllChats, setShowAllChats] = useState(false);
  const settingsControlRef = useRef<HTMLDivElement>(null);
  const logsControlRef = useRef<HTMLDivElement>(null);
  const isRunRoute = location.pathname.startsWith('/runs/');
  const headerTitle = overrideTitle || '';
  const visibleHistory = showAllChats ? history : history.slice(0, 10);
  const hasExtraChats = history.length > 10;
  const sideContentClasses = [
    isRunRoute ? REPORT_SIDE_CONTENT_CLASSES : HOME_SIDE_CONTENT_CLASSES,
    navOpen ? SIDE_CONTENT_OPEN_CLASSES : SIDE_CONTENT_COLLAPSED_CLASSES,
  ].join(' ');
  const chatListClasses = isRunRoute
    ? REPORT_CHAT_LIST_CLASSES
    : HOME_CHAT_LIST_CLASSES;
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
    'google-app-shell',
    isRunRoute ? 'report-shell' : 'home-shell',
    navOpen ? SHELL_OPEN_GRID_CLASSES : SHELL_COLLAPSED_GRID_CLASSES,
    'min-h-screen',
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
    window.dispatchEvent(new Event('cosci-new-chat'));
    void navigate('/', {state: {cosciAction: 'new-chat'}});
  }

  function focusComposer() {
    window.dispatchEvent(new Event('cosci-focus-composer'));
    void navigate('/', {state: {cosciAction: 'focus-composer'}});
  }

  function toggleNav() {
    setNavOpen(open => !open);
    setActivePanel(null);
  }

  function togglePanel(panel: ShellPanel) {
    setActivePanel(current => (current === panel ? null : panel));
  }

  useEffect(() => {
    setOverrideTitle('');
    setActivePanel(null);
  }, [location.pathname]);

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
            <NavActionButton
              label="Search"
              icon="search"
              className={navItemClasses}
              labelClassName={navLabelClasses}
              onClick={focusComposer}
            />
          </nav>
          <div className={sideContentClasses}>
            <p className={SIDE_HEADING_CLASSES}>Chats</p>
            <div className={chatListClasses}>
              {visibleHistory.map(run => (
                <Link
                  key={run.id}
                  to={`/runs/${run.id}/details`}
                  className={tooltipClassNames({
                    className: CHAT_HISTORY_LINK_CLASSES,
                    placement: 'right',
                    wrap: true,
                  })}
                  data-tooltip={run.research_goal}
                >
                  <span className={CHAT_HISTORY_LABEL_CLASSES}>
                    {conciseTitle(run.research_goal)}
                  </span>
                </Link>
              ))}
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
              navOpen ? 'w-full' : 'w-auto'
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
      <section className={workspaceClasses}>
        <header className={HEADER_CLASSES}>
          <button
            type="button"
            className={PRODUCT_LOCKUP_CLASSES}
            aria-label="Go to Co-Scientist home"
            onClick={startNewChat}
          >
            <GoogleLabsIcon aria-hidden="true" />
            <span>Co-Scientist</span>
          </button>
          <div className={HEADER_TITLE_CLASSES}>{headerTitle}</div>
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

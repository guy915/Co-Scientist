import '@material/web/icon/icon.js';
import '@material/web/iconbutton/icon-button.js';
import {useEffect, useRef, useState, type ReactNode} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {listDemoRuns, listRuns, type Run} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {useTheme} from './theme_context';
import {tooltipClassNames} from './tooltip';

type ShellPanel = 'settings' | 'logs';

type DiagnosticLogLevel = 'info' | 'success' | 'error';

interface DiagnosticLogEntry {
  id: number;
  time: string;
  run: string;
  stage: string;
  level: DiagnosticLogLevel;
  payload: Record<string, unknown>;
}

interface DiagnosticLogEventDetail {
  run?: string;
  stage: string;
  level?: DiagnosticLogLevel;
  payload?: Record<string, unknown>;
}

const LOGS_POPOVER_CLASSES = [
  'ucs-popover--logs',
  'top-[calc(100%+0.45rem)] right-0 !w-[min(32rem,calc(100vw-2rem))]',
  'max-h-[min(32rem,calc(100vh-6rem))] grid-rows-[auto_auto_minmax(0,1fr)]',
  '!gap-0 overflow-hidden !p-0 dark:!border-[#33363b] dark:!bg-[#17181b]',
  'max-[720px]:right-[-0.5rem] max-[720px]:!w-[min(18.5rem,calc(100vw-1.5rem))]',
].join(' ');

const DIAGNOSTIC_HEADER_CLASSES =
  'ucs-diagnostic-header flex items-center justify-between gap-3 border-b ' +
  'border-[#dfe3e7] px-4 py-3 dark:border-[#33363b] ' +
  'max-[720px]:flex-col max-[720px]:items-start';

const DIAGNOSTIC_INTRO_CLASSES =
  'ucs-diagnostic-intro border-b border-[#dfe3e7] px-4 py-3 ' +
  'dark:border-[#33363b]';

const DIAGNOSTIC_TITLE_CLASSES =
  'm-0 text-base font-semibold leading-tight text-[#202124] ' +
  'dark:text-[#f1f3f4]';

const DIAGNOSTIC_ACTIONS_CLASSES =
  'ucs-diagnostic-actions flex flex-nowrap gap-[0.45rem]';

const DIAGNOSTIC_ACTION_BUTTON_CLASSES =
  'inline-flex min-h-8 cursor-pointer items-center gap-[0.3rem] rounded-full ' +
  'border border-[#9accc3] bg-white px-[0.7rem] text-[0.82rem] ' +
  'font-semibold whitespace-nowrap text-[#0f5454] dark:border-[#315e57] ' +
  'dark:bg-[#173b3b] dark:text-[#7fd7bf]';

const DIAGNOSTIC_CHIPS_CLASSES =
  'ucs-diagnostic-chips flex flex-wrap gap-[0.45rem]';

const DIAGNOSTIC_CHIP_CLASSES =
  'rounded-full bg-[#e0f2ef] px-2 py-[0.15rem] text-[0.7rem] font-semibold ' +
  'whitespace-nowrap text-[#0f5454] dark:bg-[#173b3b] dark:text-[#7fd7bf]';

const DIAGNOSTIC_ERROR_CHIP_CLASSES =
  'rounded-full bg-[#f8d6d2] px-2 py-[0.15rem] text-[0.7rem] font-semibold ' +
  'whitespace-nowrap text-[#9b1c13] dark:bg-[#5b2b2b] dark:text-[#ffb4aa]';

const DIAGNOSTIC_LIST_CLASSES =
  'ucs-diagnostic-list grid min-h-0 gap-2 overflow-auto px-4 pt-3 pb-4 ' +
  '[scrollbar-color:#cfd8dc_transparent] [scrollbar-width:thin]';

const DIAGNOSTIC_ENTRY_CLASSES = 'ucs-diagnostic-entry grid gap-1';

const DIAGNOSTIC_ENTRY_META_CLASSES =
  'ucs-diagnostic-entry-meta grid grid-cols-[auto_auto_minmax(0,1fr)_auto] ' +
  'items-center gap-2 text-[0.72rem] font-semibold text-[#4f5358] ' +
  'dark:text-[#bdc1c6] max-[720px]:grid-cols-[auto_auto_minmax(0,1fr)]';

const DIAGNOSTIC_ENTRY_RUN_CLASSES = 'truncate';

const DIAGNOSTIC_ENTRY_STAGE_CLASSES =
  'max-[720px]:col-start-2 max-[720px]:col-end-[-1]';

const DIAGNOSTIC_CODE_CLASSES =
  'm-0 max-h-20 overflow-auto rounded-[0.55rem] bg-[#edf7f4] px-[0.7rem] ' +
  'py-[0.55rem] font-mono text-[0.72rem] leading-[1.3] text-[#202124] ' +
  'dark:bg-[#132927] dark:text-[#f1f3f4]';

const DIAGNOSTIC_EMPTY_CLASSES =
  'ucs-diagnostic-empty m-0 rounded-[0.55rem] bg-[#edf7f4] px-[0.7rem] ' +
  'py-[0.55rem] text-center text-[#0f5454] dark:bg-[#132927] ' +
  'dark:text-[#7fd7bf]';

const WORKSPACE_CLASSES = 'ucs-workspace';

const REPORT_WORKSPACE_CLASSES = 'ucs-workspace min-h-screen !overflow-hidden';

const PAGE_CLASSES = 'ucs-page';

const REPORT_PAGE_CLASSES =
  'ucs-page !h-[calc(100vh-4.5rem)] min-h-0 !overflow-hidden !p-0';

const SIDE_CONTENT_BASE_CLASSES =
  'gemini-side-content grid min-w-0 gap-[0.35rem] overflow-hidden opacity-100 visible';

const HOME_SIDE_CONTENT_CLASSES = `${SIDE_CONTENT_BASE_CLASSES} mt-[0.85rem] max-h-72`;

const REPORT_SIDE_CONTENT_CLASSES = `${SIDE_CONTENT_BASE_CLASSES} mt-6 max-h-80`;

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

function formatDiagnosticTime(date = new Date()): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  }).format(date);
}

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
  const [diagnosticLogs, setDiagnosticLogs] = useState<DiagnosticLogEntry[]>(
    [],
  );
  const [logsCopied, setLogsCopied] = useState(false);
  const [showAllChats, setShowAllChats] = useState(false);
  const nextDiagnosticId = useRef(1);
  const settingsControlRef = useRef<HTMLDivElement>(null);
  const logsControlRef = useRef<HTMLDivElement>(null);
  const isRunRoute = location.pathname.startsWith('/runs/');
  const headerTitle = overrideTitle || '';
  const visibleLogEntries = diagnosticLogs;
  const logCount = visibleLogEntries.length;
  const errorLogCount = visibleLogEntries.filter(
    entry => entry.level === 'error',
  ).length;
  const successLogCount = visibleLogEntries.filter(
    entry => entry.level === 'success',
  ).length;
  const infoLogCount = visibleLogEntries.filter(
    entry => entry.level === 'info',
  ).length;
  const runLogCount = new Set(
    visibleLogEntries.map(entry => entry.run).filter(Boolean),
  ).size;
  const visibleHistory = showAllChats ? history : history.slice(0, 10);
  const hasExtraChats = history.length > 10;
  const sideContentClasses = isRunRoute
    ? REPORT_SIDE_CONTENT_CLASSES
    : HOME_SIDE_CONTENT_CLASSES;
  const chatListClasses = isRunRoute
    ? REPORT_CHAT_LIST_CLASSES
    : HOME_CHAT_LIST_CLASSES;
  const workspaceClasses = isRunRoute
    ? REPORT_WORKSPACE_CLASSES
    : WORKSPACE_CLASSES;
  const pageClasses = isRunRoute ? REPORT_PAGE_CLASSES : PAGE_CLASSES;
  const shellClass = [
    'google-app-shell',
    isRunRoute ? 'report-shell' : 'home-shell',
    navOpen ? 'nav-open' : 'nav-collapsed',
    'min-h-screen',
  ].join(' ');

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

  function clearLogs() {
    nextDiagnosticId.current = 1;
    setDiagnosticLogs([]);
    setLogsCopied(false);
  }

  async function copyLogs() {
    const text = JSON.stringify(visibleLogEntries, null, 2);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error('Clipboard API unavailable');
      }
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.append(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }
    setLogsCopied(true);
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
    function onDiagnosticEvent(event: Event) {
      const custom = event as CustomEvent<DiagnosticLogEventDetail>;
      if (!custom.detail?.stage) return;
      const entry: DiagnosticLogEntry = {
        id: nextDiagnosticId.current,
        time: formatDiagnosticTime(),
        run: custom.detail.run || 'Current session',
        stage: custom.detail.stage,
        level: custom.detail.level || 'info',
        payload: custom.detail.payload || {},
      };
      nextDiagnosticId.current += 1;
      setDiagnosticLogs(current => [...current, entry]);
      setLogsCopied(false);
    }
    window.addEventListener('cosci-diagnostic-event', onDiagnosticEvent);
    return () => {
      window.removeEventListener('cosci-diagnostic-event', onDiagnosticEvent);
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
      <aside className="ucs-nav-panel" aria-label="Primary navigation">
        <div className="ucs-nav-top">
          <button
            type="button"
            className={tooltipClassNames({
              className: 'ucs-nav-item',
              placement: 'right',
            })}
            aria-label="Menu"
            data-tooltip="Menu"
            aria-expanded={navOpen}
            aria-controls="primary-navigation"
            onClick={toggleNav}
          >
            <md-icon aria-hidden="true">menu</md-icon>
            <span className="nav-label">Menu</span>
          </button>
          <nav id="primary-navigation" className="ucs-nav-items">
            <button
              type="button"
              className={tooltipClassNames({
                className: 'ucs-nav-item',
                placement: 'right',
              })}
              aria-label="New chat"
              data-tooltip="New chat"
              onClick={startNewChat}
            >
              <md-icon aria-hidden="true">edit_square</md-icon>
              <span className="nav-label">New chat</span>
            </button>
            <button
              type="button"
              className={tooltipClassNames({
                className: 'ucs-nav-item',
                placement: 'right',
              })}
              aria-label="Search"
              data-tooltip="Search"
              onClick={focusComposer}
            >
              <md-icon aria-hidden="true">search</md-icon>
              <span className="nav-label">Search</span>
            </button>
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
        <div className="ucs-nav-bottom">
          <div ref={settingsControlRef} className="ucs-settings-control">
            <button
              type="button"
              className={tooltipClassNames({
                className: 'ucs-nav-item',
                placement: 'right',
              })}
              aria-label="Settings"
              data-tooltip="Settings"
              aria-expanded={activePanel === 'settings'}
              onClick={() => togglePanel('settings')}
            >
              <md-icon aria-hidden="true">settings</md-icon>
              <span className="nav-label">Settings</span>
            </button>
            {activePanel === 'settings' && (
              <ShellPopover className="ucs-popover--rail">
                <div
                  className="ucs-theme-segment ucs-theme-segment--inline"
                  role="group"
                  aria-label="Theme"
                >
                  <ThemeModeButton
                    mode="system"
                    active={mode === 'system'}
                    icon="computer"
                    label="System"
                    onModeChange={setMode}
                  />
                  <ThemeModeButton
                    mode="light"
                    active={mode === 'light'}
                    icon="light_mode"
                    label="Light"
                    onModeChange={setMode}
                  />
                  <ThemeModeButton
                    mode="dark"
                    active={mode === 'dark'}
                    icon="dark_mode"
                    label="Dark"
                    onModeChange={setMode}
                  />
                </div>
              </ShellPopover>
            )}
          </div>
        </div>
      </aside>
      <section className={workspaceClasses}>
        <header className="ucs-header-action-bar">
          <button
            type="button"
            className="ucs-product-lockup"
            aria-label="Go to Co-Scientist home"
            onClick={startNewChat}
          >
            <GoogleLabsIcon aria-hidden="true" />
            <span>Co-Scientist</span>
          </button>
          <div className="ucs-header-title">{headerTitle}</div>
          <div ref={logsControlRef} className="ucs-header-actions">
            <button
              type="button"
              className="ucs-logs-button"
              aria-label={`Logs ${logCount}`}
              aria-expanded={activePanel === 'logs'}
              onClick={() => togglePanel('logs')}
            >
              <md-icon aria-hidden="true">expand_more</md-icon>
              <span>Logs</span>
              <span className="ucs-logs-count">{logCount}</span>
            </button>
            {activePanel === 'logs' && (
              <ShellPopover className={LOGS_POPOVER_CLASSES}>
                <div className={DIAGNOSTIC_HEADER_CLASSES}>
                  <div className="ucs-diagnostic-title">
                    <h2 className={DIAGNOSTIC_TITLE_CLASSES}>
                      Diagnostic Logs
                    </h2>
                  </div>
                  <div className={DIAGNOSTIC_ACTIONS_CLASSES}>
                    <button
                      type="button"
                      className={DIAGNOSTIC_ACTION_BUTTON_CLASSES}
                      onClick={clearLogs}
                    >
                      <md-icon aria-hidden="true" className="text-base">
                        refresh
                      </md-icon>
                      <span>Clear</span>
                    </button>
                    <button
                      type="button"
                      className={DIAGNOSTIC_ACTION_BUTTON_CLASSES}
                      onClick={copyLogs}
                    >
                      <md-icon aria-hidden="true" className="text-base">
                        content_copy
                      </md-icon>
                      <span>{logsCopied ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                </div>
                <div className={DIAGNOSTIC_INTRO_CLASSES}>
                  <div className={DIAGNOSTIC_CHIPS_CLASSES}>
                    <span className={DIAGNOSTIC_CHIP_CLASSES}>
                      Total {logCount}
                    </span>
                    <span
                      className={
                        errorLogCount
                          ? DIAGNOSTIC_ERROR_CHIP_CLASSES
                          : DIAGNOSTIC_CHIP_CLASSES
                      }
                    >
                      Errors {errorLogCount}
                    </span>
                    <span className={DIAGNOSTIC_CHIP_CLASSES}>
                      Success {successLogCount}
                    </span>
                    <span className={DIAGNOSTIC_CHIP_CLASSES}>
                      Info {infoLogCount}
                    </span>
                    <span className={DIAGNOSTIC_CHIP_CLASSES}>
                      Runs {runLogCount}
                    </span>
                  </div>
                </div>
                <div
                  className={DIAGNOSTIC_LIST_CLASSES}
                  aria-label="Log events"
                >
                  {visibleLogEntries.map(entry => (
                    <article
                      key={entry.id}
                      className={DIAGNOSTIC_ENTRY_CLASSES}
                    >
                      <div className={DIAGNOSTIC_ENTRY_META_CLASSES}>
                        <span>#{entry.id}</span>
                        <span>[{entry.time}]</span>
                        <span className={DIAGNOSTIC_ENTRY_RUN_CLASSES}>
                          {entry.run}
                        </span>
                        <strong className={DIAGNOSTIC_ENTRY_STAGE_CLASSES}>
                          {entry.stage}:
                        </strong>
                      </div>
                      <pre className={DIAGNOSTIC_CODE_CLASSES}>
                        {JSON.stringify(entry.payload, null, 2)}
                      </pre>
                    </article>
                  ))}
                  {visibleLogEntries.length === 0 && (
                    <p className={DIAGNOSTIC_EMPTY_CLASSES}>
                      No diagnostic events loaded.
                    </p>
                  )}
                </div>
              </ShellPopover>
            )}
          </div>
        </header>
        <main className={pageClasses}>{children}</main>
      </section>
    </div>
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
  icon: string;
  label: string;
  onModeChange: (mode: 'system' | 'light' | 'dark') => void;
}) {
  return (
    <button
      type="button"
      className={active ? 'selected' : ''}
      aria-pressed={active}
      onClick={() => onModeChange(mode)}
    >
      <md-icon aria-hidden="true">{icon}</md-icon>
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
    <div className={`ucs-popover ${className}`} role="status">
      {children}
    </div>
  );
}

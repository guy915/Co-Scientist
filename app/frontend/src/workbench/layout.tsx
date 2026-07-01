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
          <div className="gemini-side-content">
            <p className="gemini-side-heading">Chats</p>
            <div className="gemini-chat-list">
              {visibleHistory.map(run => (
                <Link
                  key={run.id}
                  to={`/runs/${run.id}/details`}
                  className={tooltipClassNames({
                    placement: 'right',
                    wrap: true,
                  })}
                  data-tooltip={run.research_goal}
                >
                  <span>{conciseTitle(run.research_goal)}</span>
                </Link>
              ))}
              {hasExtraChats && (
                <button
                  type="button"
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
      <section className="ucs-workspace">
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
              <ShellPopover className="ucs-popover--logs">
                <div className="ucs-diagnostic-header">
                  <div className="ucs-diagnostic-title">
                    <h2>Diagnostic Logs</h2>
                  </div>
                  <div className="ucs-diagnostic-actions">
                    <button type="button" onClick={clearLogs}>
                      <md-icon aria-hidden="true">refresh</md-icon>
                      <span>Clear</span>
                    </button>
                    <button type="button" onClick={copyLogs}>
                      <md-icon aria-hidden="true">content_copy</md-icon>
                      <span>{logsCopied ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                </div>
                <div className="ucs-diagnostic-intro">
                  <div className="ucs-diagnostic-chips">
                    <span>Total {logCount}</span>
                    <span className={errorLogCount ? 'error' : undefined}>
                      Errors {errorLogCount}
                    </span>
                    <span>Success {successLogCount}</span>
                    <span>Info {infoLogCount}</span>
                    <span>Runs {runLogCount}</span>
                  </div>
                </div>
                <div className="ucs-diagnostic-list" aria-label="Log events">
                  {visibleLogEntries.map(entry => (
                    <article key={entry.id} className="ucs-diagnostic-entry">
                      <div className="ucs-diagnostic-entry-meta">
                        <span>#{entry.id}</span>
                        <span>[{entry.time}]</span>
                        <span>{entry.run}</span>
                        <strong>{entry.stage}:</strong>
                      </div>
                      <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
                    </article>
                  ))}
                  {visibleLogEntries.length === 0 && (
                    <p className="ucs-diagnostic-empty">
                      No diagnostic events loaded.
                    </p>
                  )}
                </div>
              </ShellPopover>
            )}
          </div>
        </header>
        <main className="ucs-page">{children}</main>
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

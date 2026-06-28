import '@material/web/icon/icon.js';
import '@material/web/iconbutton/icon-button.js';
import {useEffect, useRef, useState, type ReactNode} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {listDemoRuns, listRuns, type Run} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {useTheme} from './theme_context';

type ShellPanel = 'settings' | 'logs';

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
  const settingsControlRef = useRef<HTMLDivElement>(null);
  const logsControlRef = useRef<HTMLDivElement>(null);
  const isRunRoute = location.pathname.startsWith('/runs/');
  const headerTitle = overrideTitle || '';
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
      <aside className="ucs-nav-panel" aria-label="Primary navigation">
        <div className="ucs-nav-top">
          <button
            type="button"
            className="ucs-rail-button"
            aria-label="Menu"
            data-tooltip="Menu"
            aria-expanded={navOpen}
            aria-controls="primary-navigation"
            onClick={toggleNav}
          >
            <md-icon aria-hidden="true">menu</md-icon>
          </button>
          <nav id="primary-navigation" className="ucs-nav-items">
            <button
              type="button"
              className="ucs-nav-item selected"
              title="New chat"
              aria-label="New chat"
              data-tooltip="New chat"
              onClick={startNewChat}
            >
              <md-icon aria-hidden="true">edit_square</md-icon>
              <span className="nav-label">New chat</span>
            </button>
            <button
              type="button"
              className="ucs-nav-item"
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
              {history.slice(0, 4).map(run => (
                <Link key={run.id} to={`/runs/${run.id}/details`}>
                  {conciseTitle(run.research_goal)}
                </Link>
              ))}
            </div>
          </div>
        </div>
        <div className="ucs-nav-bottom">
          <div ref={settingsControlRef} className="ucs-settings-control">
            <button
              type="button"
              className="ucs-rail-button"
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
                <div className="ucs-settings-theme-block">
                  <div className="ucs-settings-menu-row ucs-settings-menu-heading">
                    <md-icon aria-hidden="true">palette</md-icon>
                    <span>Appearance</span>
                  </div>
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
                </div>
                <button
                  type="button"
                  className="ucs-settings-menu-row ucs-settings-help-row"
                >
                  <md-icon aria-hidden="true">help</md-icon>
                  <span>Get help</span>
                </button>
              </ShellPopover>
            )}
          </div>
        </div>
      </aside>
      <section className="ucs-workspace">
        <header className="ucs-header-action-bar">
          <Link to="/" className="ucs-product-lockup">
            <GoogleLabsIcon aria-hidden="true" />
            <span>Co-Scientist</span>
          </Link>
          <div className="ucs-header-title">{headerTitle}</div>
          <div ref={logsControlRef} className="ucs-header-actions">
            <button
              type="button"
              className="ucs-logs-button"
              aria-label="Logs 23"
              data-tooltip="Logs"
              aria-expanded={activePanel === 'logs'}
              onClick={() => togglePanel('logs')}
            >
              <md-icon aria-hidden="true">expand_more</md-icon>
              <span>Logs</span>
              <span className="ucs-logs-count">23</span>
            </button>
            {activePanel === 'logs' && (
              <ShellPopover className="ucs-popover--logs">
                <div className="ucs-logs-menu-heading">
                  <span>Logs</span>
                  <span>23</span>
                </div>
                <div className="ucs-logs-menu-list">
                  <span>Supervisor scoped the research goal</span>
                  <span>Literature review gathered evidence</span>
                  <span>Tournament ranking completed</span>
                </div>
              </ShellPopover>
            )}
          </div>
        </header>
        <main className="ucs-page wb-fade-in">{children}</main>
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

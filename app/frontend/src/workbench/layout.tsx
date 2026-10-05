import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react';
import {useLocation} from 'react-router-dom';
import type {RunStatus} from '@/api/runs';
import {joinClasses} from './classes';
import {useRunHistoryContext} from './hooks/history_context';
import {
  SettingsDialog,
  type SettingsSection,
} from './components/settings_dialog';
import {NEW_CHAT_EVENT, HEADER_TITLE_EVENT} from './dom_events';
import {closeDrawerIfMobile, useEscapeKey} from './hooks/dom';
import {ShellHeader} from './layout_header';
import {
  NavRail,
  withExampleEntries,
  type ChatRailData,
} from './layout_nav_rail';
import {
  sessionSwitchData,
  type SessionSwitchData,
} from './layout_session_switch';
import {useChatHistoryContext} from './hooks/history_context';

type LayoutChrome = ReturnType<typeof useLayoutChrome>;

const WORKSPACE_CLASSES = 'ucs-workspace';

const WORKSPACE_RESPONSIVE_CLASSES = 'ucs-workspace--rounded-bottom';

const REPORT_WORKSPACE_CLASSES = 'ucs-workspace ucs-workspace--report';

const PAGE_CLASSES = 'ucs-page';

const HOME_PAGE_CLASSES = 'ucs-page ucs-page--home';

const REPORT_PAGE_CLASSES = 'ucs-page ucs-page--report';

const SHELL_OPEN_GRID_CLASSES = 'nav-open';

const SHELL_COLLAPSED_GRID_CLASSES = 'nav-collapsed';

function pageClassesFor(pathname: string, isRunRoute: boolean): string {
  if (isRunRoute) return REPORT_PAGE_CLASSES;
  return pathname === '/' ? HOME_PAGE_CLASSES : PAGE_CLASSES;
}

function deriveRoutePresentation(pathname: string): {
  isRunRoute: boolean;
  activeRunId: string | undefined;
  activeChatId: string | undefined;
  titleContextKey: string;
  workspaceClasses: string;
  pageClasses: string;
} {
  const isRunRoute = pathname.startsWith('/runs/');
  const activeRunId = isRunRoute ? pathname.split('/')[2] : undefined;
  const activeChatId = pathname.startsWith('/chats/')
    ? pathname.split('/')[2]
    : undefined;
  // Tab changes keep RunDetail mounted and do not redispatch its title; clear
  // only when the title-owning context changes.
  const titleContextKey = isRunRoute ? `run:${activeRunId}` : pathname;
  const workspaceClasses = isRunRoute
    ? REPORT_WORKSPACE_CLASSES
    : `${WORKSPACE_CLASSES} ${WORKSPACE_RESPONSIVE_CLASSES}`;

  return {
    isRunRoute,
    activeRunId,
    activeChatId,
    titleContextKey,
    workspaceClasses,
    pageClasses: pageClassesFor(pathname, isRunRoute),
  };
}

function shellClassFor(isRunRoute: boolean, navOpen: boolean): string {
  return joinClasses(
    'ucs-app-shell',
    isRunRoute ? 'report-shell' : 'home-shell',
    navOpen ? SHELL_OPEN_GRID_CLASSES : SHELL_COLLAPSED_GRID_CLASSES,
  );
}

// Navigation belongs to real links; reset only the current tab and dismiss
// mobile overlays while preserving desktop rail preference.
function createStartNewChatHandler(
  setNavOpen: (open: boolean) => void,
): () => void {
  return () => {
    closeDrawerIfMobile(setNavOpen);
    window.dispatchEvent(new Event(NEW_CHAT_EVENT));
  };
}

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

interface ShellOverlaysProps {
  chrome: LayoutChrome;
}

function ShellOverlays({chrome}: ShellOverlaysProps) {
  const {settingsSection, setSettingsSection} = chrome;
  if (!settingsSection) return null;
  return (
    <SettingsDialog
      section={settingsSection}
      onSectionChange={setSettingsSection}
      onClose={() => setSettingsSection(null)}
    />
  );
}

interface ShellNavProps {
  chrome: LayoutChrome;
  startNewChat: () => void;
  rail: ChatRailData;
}

function ShellNav({chrome, startNewChat, rail}: ShellNavProps) {
  return (
    <>
      <NavRail
        navOpen={chrome.navOpen}
        toggleNav={chrome.toggleNav}
        startNewChat={startNewChat}
        rail={rail}
        activePanel={chrome.activePanel}
        onTogglePanel={chrome.togglePanel}
        onOpenSettings={chrome.openSettings}
        settingsControlRef={chrome.settingsControlRef}
      />
      <DrawerScrim
        navOpen={chrome.navOpen}
        onDismiss={() => chrome.setNavOpen(false)}
      />
    </>
  );
}

interface ShellWorkspaceProps {
  chrome: LayoutChrome;
  startNewChat: () => void;
  headerTitle: string;
  session: SessionSwitchData | null;
  runStatus: RunStatus | undefined;
  workspaceClasses: string;
  pageClasses: string;
  children: ReactNode;
}

function ShellWorkspace({
  chrome,
  startNewChat,
  headerTitle,
  session,
  runStatus,
  workspaceClasses,
  pageClasses,
  children,
}: ShellWorkspaceProps) {
  return (
    <section className={workspaceClasses}>
      <ShellHeader
        navOpen={chrome.navOpen}
        toggleNav={chrome.toggleNav}
        startNewChat={startNewChat}
        headerTitle={headerTitle}
        session={session}
        runStatus={runStatus}
        activePanel={chrome.activePanel}
        onTogglePanel={chrome.togglePanel}
        logsControlRef={chrome.logsControlRef}
      />
      <main className={pageClasses}>{children}</main>
    </section>
  );
}

function useLayoutState() {
  const location = useLocation();
  const {
    isRunRoute,
    activeRunId,
    activeChatId,
    titleContextKey,
    workspaceClasses,
    pageClasses,
  } = deriveRoutePresentation(location.pathname);
  const headerTitle = useHeaderTitle(titleContextKey);
  const {chats, showAllChats, toggleShowAllChats} = useChatHistory();
  const chrome = useLayoutChrome(location.pathname);
  const {history} = useRunHistoryContext();
  const session = sessionSwitchData(chats, activeChatId, activeRunId);
  // Shared history already polls active runs; avoid a second status request for
  // header controls.
  const runStatus = history.find(run => run.id === session?.runId)?.status;
  const shellClass = shellClassFor(isRunRoute, chrome.navOpen);
  const startNewChat = createStartNewChatHandler(chrome.setNavOpen);

  return {
    shellClass,
    chrome,
    startNewChat,
    rail: {
      chats: withExampleEntries(chats, history),
      activeChatId,
      activeRunId,
      showAllChats,
      onToggleShowAllChats: toggleShowAllChats,
    },
    headerTitle,
    session,
    runStatus,
    workspaceClasses,
    pageClasses,
  };
}

export function Layout({children}: {children: ReactNode}) {
  const state = useLayoutState();

  return (
    <div className={state.shellClass}>
      <ShellNav
        chrome={state.chrome}
        startNewChat={state.startNewChat}
        rail={state.rail}
      />
      <ShellWorkspace
        chrome={state.chrome}
        startNewChat={state.startNewChat}
        headerTitle={state.headerTitle}
        session={state.session}
        runStatus={state.runStatus}
        workspaceClasses={state.workspaceClasses}
        pageClasses={state.pageClasses}
      >
        {children}
      </ShellWorkspace>
      <ShellOverlays chrome={state.chrome} />
    </div>
  );
}

export type ShellPanel = 'settings' | 'logs';

// Chats enter history from their first turn, whether or not they become runs.
export function useChatHistory() {
  const {chats} = useChatHistoryContext();
  const [showAllChats, setShowAllChats] = useState(false);

  return {
    chats,
    showAllChats,
    toggleShowAllChats: () => setShowAllChats(current => !current),
  };
}

export function useHeaderTitle(contextKey: string): string {
  const [overrideTitle, setOverrideTitle] = useState('');

  useEffect(() => {
    setOverrideTitle('');
  }, [contextKey]);

  useEffect(() => {
    function onHeaderTitle(event: Event) {
      const custom = event as CustomEvent<string>;
      setOverrideTitle(custom.detail || '');
    }
    window.addEventListener(HEADER_TITLE_EVENT, onHeaderTitle);
    return () => {
      window.removeEventListener(HEADER_TITLE_EVENT, onHeaderTitle);
    };
  }, []);

  return overrideTitle;
}

// Navigating must dismiss overlays; desktop rail expansion remains a user
// preference.
function useDismissChromeOnNavigate(
  pathname: string,
  setActivePanel: (panel: ShellPanel | null) => void,
  setNavOpen: (open: boolean) => void,
) {
  useEffect(() => {
    setActivePanel(null);
    closeDrawerIfMobile(setNavOpen);
  }, [pathname]);
}

function useEscapeClosesDrawer(
  navOpen: boolean,
  setNavOpen: (open: boolean) => void,
) {
  const closeDrawer = useCallback(
    () => closeDrawerIfMobile(setNavOpen),
    [setNavOpen],
  );
  useEscapeKey(closeDrawer, navOpen);
}

// Subscribe globally only while a popover is open, so idle shell renders carry
// no outside-pointer listener.
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

function useChromeActions(
  setNavOpen: Dispatch<SetStateAction<boolean>>,
  setActivePanel: Dispatch<SetStateAction<ShellPanel | null>>,
  setSettingsSection: Dispatch<SetStateAction<SettingsSection | null>>,
) {
  function toggleNav() {
    setNavOpen(open => !open);
    setActivePanel(null);
  }

  function togglePanel(panel: ShellPanel) {
    setActivePanel(current => (current === panel ? null : panel));
  }

  function openSettings(section: SettingsSection) {
    setActivePanel(null);
    // Close the underlying mobile drawer so dismissing Settings cannot reveal a
    // stale overlay.
    closeDrawerIfMobile(setNavOpen);
    setSettingsSection(section);
  }

  return {toggleNav, togglePanel, openSettings};
}

function useChromeState() {
  const [navOpen, setNavOpen] = useState(false);
  const [activePanel, setActivePanel] = useState<ShellPanel | null>(null);
  const [settingsSection, setSettingsSection] =
    useState<SettingsSection | null>(null);
  const settingsControlRef = useRef<HTMLDivElement>(null);
  const logsControlRef = useRef<HTMLDivElement>(null);

  return {
    navOpen,
    setNavOpen,
    activePanel,
    setActivePanel,
    settingsSection,
    setSettingsSection,
    settingsControlRef,
    logsControlRef,
  };
}

export function useLayoutChrome(pathname: string) {
  const state = useChromeState();
  const {navOpen, activePanel, setActivePanel, setNavOpen} = state;
  const {settingsControlRef, logsControlRef} = state;

  const {toggleNav, togglePanel, openSettings} = useChromeActions(
    setNavOpen,
    setActivePanel,
    state.setSettingsSection,
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
    settingsSection: state.settingsSection,
    setSettingsSection: state.setSettingsSection,
    settingsControlRef,
    logsControlRef,
    toggleNav,
    togglePanel,
    openSettings,
  };
}

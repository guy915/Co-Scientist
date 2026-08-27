import {type ReactNode} from 'react';
import {useLocation} from 'react-router-dom';
import {type RunStatus} from '@/api/runs';
import {joinClasses} from './classes';
import {useRunHistoryContext} from './hooks/run_history_context';
import {SettingsDialog} from './components/settings_dialog';
import {NEW_CHAT_EVENT} from './dom_events';
import {closeDrawerIfMobile} from './hooks/use_is_mobile';
import {ShellHeader} from './layout_header';
import {useChatHistory, useHeaderTitle, useLayoutChrome} from './layout_hooks';
import {NavRail, type ChatRailData} from './layout_nav_rail';
import {
  sessionSwitchData,
  type SessionSwitchData,
} from './layout_session_switch';

// The value returned by useLayoutChrome, threaded through the components
// below so each only needs the single prop rather than the whole fan-out.
type LayoutChrome = ReturnType<typeof useLayoutChrome>;

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
  activeChatId: string | undefined;
  titleContextKey: string;
  workspaceClasses: string;
  pageClasses: string;
} {
  const isRunRoute = pathname.startsWith('/runs/');
  // The run id embedded in /runs/:id[/:tab], used to persistently highlight the
  // active conversation in the sidebar chat list.
  const activeRunId = isRunRoute ? pathname.split('/')[2] : undefined;
  // The chat id embedded in /chats/:id, which highlights the rail row
  // directly rather than through the run a chat may have started.
  const activeChatId = pathname.startsWith('/chats/')
    ? pathname.split('/')[2]
    : undefined;
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
    activeChatId,
    titleContextKey,
    workspaceClasses,
    pageClasses: pageClassesFor(pathname, isRunRoute),
  };
}

// The shell root's classes: the report/home variant (route-driven, see
// deriveRoutePresentation above) and the open/collapsed grid (navOpen-driven,
// see useLayoutChrome in layout_hooks.ts). `nav-open`/`nav-collapsed` is the
// class shell_surface.css keys its responsive rules off: on desktop (>700px)
// it toggles the rail's grid column width; on mobile (<=700px) both variants
// collapse to a single full-width column and the rail instead becomes a
// fixed, off-canvas drawer that slides over the content (see the scrim below
// and the ~700px breakpoint in shell_surface.css for the iOS-safe dvh
// sizing).
function shellClassFor(isRunRoute: boolean, navOpen: boolean): string {
  return joinClasses(
    'ucs-app-shell',
    isRunRoute ? 'report-shell' : 'home-shell',
    navOpen ? SHELL_OPEN_GRID_CLASSES : SHELL_COLLAPSED_GRID_CLASSES,
  );
}

// Builds the "New chat" / product-lockup handler: resets the chat workspace
// and dismisses the mobile drawer. On desktop the expanded rail is a user
// preference, so clicking Home or New chat leaves it untouched there.
//
// Navigation itself is the link's job now (both controls are anchors, so a
// Cmd or middle click opens a fresh workspace in a new tab); this only has to
// do the part a new tab must not inherit.
function createStartNewChatHandler(
  setNavOpen: (open: boolean) => void,
): () => void {
  return () => {
    closeDrawerIfMobile(setNavOpen);
    // Lets the chat workspace page (mounted separately) know to reset its own
    // session state; see ChatWorkspace's listener.
    window.dispatchEvent(new Event(NEW_CHAT_EVENT));
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

// The full-screen Settings dialog overlay. Kept out of Layout so the
// component itself stays the thin render/wiring function documented there.
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

// The icon rail plus its mobile drawer scrim. Split out of Layout so each
// piece only needs the chrome slice it actually renders.
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

// The header plus routed page content.
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

// Everything Layout's render needs, derived from the current route: the
// route-dependent presentation, the chat-history sidebar data, the shared
// chrome state (rail/popovers/dialog), and the shell root's class.
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
  // Both halves of the session this route belongs to, so the header can
  // offer the other one (see SessionSwitch).
  const session = sessionSwitchData(chats, activeChatId, activeRunId);
  // The run's own status, for the header's Stop control. Read from the
  // shared history rather than fetched here: it already polls while any run
  // is active, so the control appears and disappears on its own.
  const runStatus = history.find(run => run.id === session?.runId)?.status;
  const shellClass = shellClassFor(isRunRoute, chrome.navOpen);
  const startNewChat = createStartNewChatHandler(chrome.setNavOpen);

  return {
    shellClass,
    chrome,
    startNewChat,
    rail: {
      chats,
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

/**
 * Renders the app shell with header navigation, main content, and footer.
 *
 * @param props The page content to render inside the layout.
 */
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

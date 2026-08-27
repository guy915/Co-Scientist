import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react';
import {type SettingsSection} from './components/settings_dialog';
import {HEADER_TITLE_EVENT} from './dom_events';
import {useChatHistoryContext} from './hooks/chat_history_context';
import {useEscapeKey} from './hooks/use_escape_key';
import {closeDrawerIfMobile} from './hooks/use_is_mobile';

/**
 * Which header popover is open. Only one can be open at a time (see
 * useLayoutChrome's togglePanel), and any open one is dismissed by an
 * outside click, Escape, or navigation.
 */
export type ShellPanel = 'settings' | 'logs';

/**
 * Sidebar chat history: the chat list (from the shared
 * {@link useChatHistoryContext}) plus the local "show more" expansion flag.
 * Chats, not runs: a conversation belongs in the rail from its first turn,
 * whether or not it ever becomes a run.
 */
export function useChatHistory() {
  const {chats} = useChatHistoryContext();
  // Collapsed, the list shows as many chats as the rail has room for; see
  // useFittingRows in layout_nav_rail.
  const [showAllChats, setShowAllChats] = useState(false);

  return {
    chats,
    showAllChats,
    toggleShowAllChats: () => setShowAllChats(current => !current),
  };
}

/**
 * The header title override dispatched by page components (e.g. RunDetail)
 * via the `cosci-header-title` CustomEvent, since the header lives in the
 * shell above the routed page content.
 *
 * @param contextKey Identifies the title-owning route (see Layout's
 *   titleContextKey) and clears any stale title when it changes.
 */
export function useHeaderTitle(contextKey: string): string {
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
    window.addEventListener(HEADER_TITLE_EVENT, onHeaderTitle);
    return () => {
      window.removeEventListener(HEADER_TITLE_EVENT, onHeaderTitle);
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
    closeDrawerIfMobile(setNavOpen);
  }, [pathname]);
}

// Escape closes the mobile drawer (a standard dismiss affordance for an
// overlay); the desktop rail is unaffected.
function useEscapeClosesDrawer(
  navOpen: boolean,
  setNavOpen: (open: boolean) => void,
) {
  // Stable handler so the shared hook only re-subscribes when `navOpen`
  // flips; an inline arrow would re-subscribe every render.
  const closeDrawer = useCallback(
    () => closeDrawerIfMobile(setNavOpen),
    [setNavOpen],
  );
  useEscapeKey(closeDrawer, navOpen);
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
    closeDrawerIfMobile(setNavOpen);
    setSettingsSection(section);
  }

  return {toggleNav, togglePanel, openSettings};
}

// The rail/popover/dialog state itself: collapsed icon rail by default,
// matching the reference product (on mobile this same flag toggles an
// off-canvas drawer instead, see shell_surface.css's <=700px breakpoint);
// which header popover is currently shown, if any (Settings/Logs are
// mutually exclusive via togglePanel); the full-screen Settings dialog's
// section; and the anchors the outside-pointerdown handler below needs.
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

/**
 * Bundles the rail's open/collapsed state, the mutually-exclusive
 * Settings/Logs popover, and the full-screen Settings dialog, plus (via the
 * sub-hooks above) the actions and effects that keep them in sync with
 * navigation, Escape, and outside clicks.
 *
 * @param pathname The current route path; navigating dismisses any open
 *   popover and the mobile drawer.
 */
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

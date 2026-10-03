import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  isActiveStatus,
  listInterviews,
  loadRunHistory,
  type ChatSummary,
  type Run,
} from '@/api/runs';
import {CHATS_CHANGED_EVENT, RUNS_CHANGED_EVENT} from '../dom_events';
import {useLocation} from 'react-router-dom';

/**
 * Owns one history list's mount/navigation/event reload lifecycle. A loader
 * may return undefined to keep the current list after a transient failure.
 * Polling stays with the provider because only run history advances itself.
 */
function useHistoryList<T>(
  load: () => Promise<T[] | undefined>,
  changedEvent: string,
) {
  const {pathname} = useLocation();
  const [items, setItems] = useState<T[]>([]);
  const mounted = useRef(false);
  const requestSequence = useRef(0);

  const reload = useCallback(async () => {
    if (!mounted.current) return;
    const request = ++requestSequence.current;
    const next = await load();
    if (
      mounted.current &&
      request === requestSequence.current &&
      next !== undefined
    ) {
      setItems(next);
    }
  }, [load]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, pathname]);

  useEffect(() => {
    window.addEventListener(changedEvent, reload);
    return () => window.removeEventListener(changedEvent, reload);
  }, [changedEvent, reload]);

  return {items, reload};
}

interface RunHistoryContextValue {
  history: Run[];
  reload: () => Promise<void>;
}

const RunHistoryContext = createContext<RunHistoryContextValue | null>(null);

// How often to re-read the history while a run is still executing. A run's
// phases last minutes, so this only has to be fast enough that the recents
// step flow does not look stuck.
const ACTIVE_RUN_REFRESH_MS = 10_000;

/**
 * Single source of truth for the run-history list, shared by the shell sidebar
 * and the home recents so the list is
 * fetched once and both surfaces stay in sync instead of holding two copies.
 *
 * Reloads on mount, on every navigation (so a run finishing elsewhere is
 * reflected without a full reload), and on the `cosci-runs-changed` signal a
 * newly created/started run dispatches -- the union of both former hooks'
 * triggers. While a run is still executing it also refreshes on a timer, since
 * none of those triggers fire as a run advances and the home recents show its
 * live progress.
 */
export function RunHistoryProvider({children}: {children: ReactNode}) {
  const {items: history, reload} = useHistoryList(
    loadRunHistory,
    RUNS_CHANGED_EVENT,
  );

  // Depend on the flag rather than `history` itself so the timer is not torn
  // down and rebuilt by the state update each refresh performs.
  const hasActiveRun = history.some(run => isActiveStatus(run.status));
  useEffect(() => {
    if (!hasActiveRun) return;
    const timer = window.setInterval(
      () => void reload(),
      ACTIVE_RUN_REFRESH_MS,
    );
    return () => {
      window.clearInterval(timer);
    };
  }, [hasActiveRun, reload]);

  return (
    <RunHistoryContext.Provider value={{history, reload}}>
      {children}
    </RunHistoryContext.Provider>
  );
}

/**
 * Reads the shared run-history context. Throws when used outside
 * {@link RunHistoryProvider}, which wraps the whole workbench shell.
 */
export function useRunHistoryContext(): RunHistoryContextValue {
  const ctx = useContext(RunHistoryContext);
  if (!ctx) {
    throw new Error(
      'useRunHistoryContext must be used within a RunHistoryProvider',
    );
  }
  return ctx;
}

interface ChatHistoryContextValue {
  chats: ChatSummary[];
  reload: () => Promise<void>;
}

const ChatHistoryContext = createContext<ChatHistoryContextValue | null>(null);

async function loadChatHistory(): Promise<ChatSummary[] | undefined> {
  try {
    return await listInterviews();
  } catch {
    // A transient list failure must not blank the rail: keep what is
    // shown and let the next navigation or signal re-sync it.
    return undefined;
  }
}

/**
 * Single source of truth for the sidebar's chat list.
 *
 * A chat is the durable interview behind a conversation, which exists from
 * the first turn onwards -- long before (and whether or not) a run is ever
 * started. It is deliberately a separate list from the run history: runs are
 * what the home cards show, chats are what the rail shows, and conflating
 * them is what left a conversation invisible until it produced a run.
 *
 * Reloads on mount, on every navigation, and on the `cosci-chats-changed`
 * signal the workspace dispatches when a chat is created or starts a run.
 * There is no timer: unlike a run, a chat only changes when this browser
 * changes it.
 */
export function ChatHistoryProvider({children}: {children: ReactNode}) {
  const {items: chats, reload} = useHistoryList(
    loadChatHistory,
    CHATS_CHANGED_EVENT,
  );

  return (
    <ChatHistoryContext.Provider value={{chats, reload}}>
      {children}
    </ChatHistoryContext.Provider>
  );
}

/**
 * Reads the shared chat-history context. Throws when used outside
 * {@link ChatHistoryProvider}, which wraps the whole workbench shell.
 */
export function useChatHistoryContext(): ChatHistoryContextValue {
  const ctx = useContext(ChatHistoryContext);
  if (!ctx) {
    throw new Error(
      'useChatHistoryContext must be used within a ChatHistoryProvider',
    );
  }
  return ctx;
}

/** Announces a chat-list change to the shared provider. */
export function announceChatsChanged(): void {
  window.dispatchEvent(new Event(CHATS_CHANGED_EVENT));
}

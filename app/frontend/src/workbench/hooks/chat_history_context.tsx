import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import {useLocation} from 'react-router-dom';
import {listInterviews, type ChatSummary} from '@/api/runs';
import {CHATS_CHANGED_EVENT} from '../dom_events';

interface ChatHistoryContextValue {
  chats: ChatSummary[];
  reload: () => Promise<void>;
}

const ChatHistoryContext = createContext<ChatHistoryContextValue | null>(null);

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
  const {pathname} = useLocation();
  const [chats, setChats] = useState<ChatSummary[]>([]);

  // Stable identity (no deps) so it can be both an effect dependency and an
  // event-listener reference, and be handed to consumers as their reload.
  const reload = useCallback(async () => {
    try {
      setChats(await listInterviews());
    } catch {
      // A transient list failure must not blank the rail: keep what is
      // shown and let the next navigation or signal re-sync it.
    }
  }, []);

  useEffect(() => {
    void reload();
    window.addEventListener(CHATS_CHANGED_EVENT, reload);
    return () => {
      window.removeEventListener(CHATS_CHANGED_EVENT, reload);
    };
  }, [reload, pathname]);

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

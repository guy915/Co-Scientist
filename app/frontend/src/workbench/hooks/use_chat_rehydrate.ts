import {useEffect, useRef} from 'react';
import {getInterview, type ChatSummary, type Run} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {type StartedSession} from '../pages/chat_timeline_cards';
import {useChatHistoryContext} from './chat_history_context';
import {useRunHistoryContext} from './run_history_context';
import {applyInterview} from './chat_session_transcript';
import {type useChatSession} from './use_chat_session';

type ChatSession = ReturnType<typeof useChatSession>;

// The label a resumed run card carries: the run's own generated title when
// the run list has it, else a clause of whichever goal text is on hand.
function startedTitle(run: Run | undefined, fallback: string): string {
  if (!run) return conciseTitle(fallback);
  return run.title?.trim() || conciseTitle(run.research_goal);
}

// The run card for a reopened chat that already started one.
function resumedSession(
  chat: ChatSummary,
  run: Run | undefined,
): StartedSession {
  return {
    id: String(chat.run_id),
    title: startedTitle(run, chat.challenge),
    at: run?.created_at ?? chat.updated_at,
  };
}

// Whether this chat is already on screen: hydrated by an earlier pass, or
// live in the session -- the first turn puts its own id in the URL, and
// reloading over that would replace a conversation with itself.
function alreadyShowing(
  session: ChatSession,
  chatId: string,
  applied: string | null,
): boolean {
  return applied === chatId || session.interview?.id === chatId;
}

/**
 * Reopens the chat named in the URL (`/chats/:id`).
 *
 * A conversation is durable server-side from its first turn, so clicking it
 * in the rail restores the real transcript rather than a summary of it. The
 * session already holding this chat is left alone: that is the case where
 * the id arrived *from* the live session (the first turn puts it in the URL),
 * and reloading over it would replace a conversation with itself.
 */
export function useChatRehydration(
  session: ChatSession,
  chatId: string | undefined,
): void {
  const {chats} = useChatHistoryContext();
  const {history} = useRunHistoryContext();
  // The chat this hook has already applied, so a re-render (or the session's
  // own updates) cannot re-fetch and stomp on live state.
  const appliedRef = useRef<string | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;

  useEffect(() => {
    const live = sessionRef.current;
    if (!chatId) {
      // Navigated back out of a chat: leave the workspace as new.
      if (appliedRef.current) live.resetSession();
      appliedRef.current = null;
      return;
    }
    if (alreadyShowing(live, chatId, appliedRef.current)) return;
    let cancelled = false;
    // try/catch around the await rather than .catch on the promise: this must
    // also survive the client throwing synchronously, which would otherwise
    // escape the effect and take the page down with it.
    void (async () => {
      try {
        const interview = await getInterview(chatId);
        if (cancelled) return;
        // Marked applied only once it actually is. Marking it up front
        // instead means React's development double-invoke cancels the first
        // pass and then short-circuits the second on its own marker, leaving
        // the chat loaded by neither.
        appliedRef.current = chatId;
        applyInterview(sessionRef.current, interview);
      } catch {
        // Deleted, or owned by another client: nothing to reopen. The rail
        // will drop the row on its next load.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chatId]);

  // The run a reopened chat started, attached once both lists are in hand.
  // Separate from the load above because the chat and run lists arrive on
  // their own schedules, and neither should hold up the transcript.
  useEffect(() => {
    const live = sessionRef.current;
    if (!chatId || live.startedSession) return;
    const chat = chats.find(entry => entry.id === chatId);
    if (!chat?.run_id) return;
    const run = history.find(entry => entry.id === chat.run_id);
    live.setStartedSession(resumedSession(chat, run));
  }, [chatId, chats, history, session.startedSession]);
}

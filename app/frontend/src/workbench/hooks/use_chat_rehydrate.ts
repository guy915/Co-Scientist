import {useEffect, useRef} from 'react';
import {
  getInterview,
  getRunMessages,
  type ChatSummary,
  type Run,
  type RunMessage,
} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {type StartedSession} from '../pages/chat_timeline_cards';
import {useChatHistoryContext} from './chat_history_context';
import {useRunHistoryContext} from './run_history_context';
import {applyInterview} from './chat_session_transcript';
import {qaMessagesToEntries} from './chat_session_qa_transcript';
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
  // The chat this hook has already fetched Q&A history for -- separate from
  // appliedRef because it depends on the run id, which arrives from the
  // chats list on its own schedule (see the third effect below).
  const qaLoadedRef = useRef<string | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;

  useEffect(() => {
    const live = sessionRef.current;
    if (!chatId) {
      // Navigated back out of a chat: leave the workspace as new.
      if (appliedRef.current) live.resetSession();
      appliedRef.current = null;
      qaLoadedRef.current = null;
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

  // A reopened chat's own Q&A exchanges: an answer that only ever lived in
  // memory would vanish on reload, so this rehydrates from the run's
  // persisted messages the same way the transcript above rehydrates the
  // interview. Keyed off the chat list's own `run_id` (not startedSession)
  // so it does not wait on the run-history lookup above to resolve.
  //
  // Gated on the interview transcript for THIS chat already being applied
  // (see readyToLoadQa): the first effect's `applyInterview` *replaces* the
  // whole message log wholesale (it is not an append), so a Q&A append that
  // lands before that replace resolves would be silently wiped out the
  // instant it does. Waiting for the replace to have already landed removes
  // the race instead of trying to win it.
  useEffect(() => {
    const live = sessionRef.current;
    if (!readyToLoadQa(chatId, qaLoadedRef.current, live.interview?.id)) {
      return;
    }
    let cancelled = false;
    void loadQaHistory(chatId, chats, qaLoadedRef, live, () => cancelled);
    return () => {
      cancelled = true;
    };
  }, [chatId, chats, session.interview]);
}

// Whether the Q&A rehydration effect above should run for this render: a
// chat is named, it has not already been fetched, and the interview
// transcript for it has landed (see the effect's own comment for why order
// matters). `chatId` narrows to `string` so the caller need not repeat the
// undefined check.
function readyToLoadQa(
  chatId: string | undefined,
  loadedFor: string | null,
  interviewId: string | undefined,
): chatId is string {
  return Boolean(chatId) && loadedFor !== chatId && interviewId === chatId;
}

// This chat's run id per the chats list, if it has one yet.
function chatRunId(chats: ChatSummary[], chatId: string): string | null {
  return chats.find(entry => entry.id === chatId)?.run_id ?? null;
}

// Marks this chat's Q&A history loaded and appends whatever rows it found
// (a no-op fetch is not an error, just nothing yet to show).
function applyQaRows(
  chatId: string,
  qaLoadedRef: {current: string | null},
  live: ChatSession,
  rows: RunMessage[],
): void {
  qaLoadedRef.current = chatId;
  const entries = qaMessagesToEntries(rows);
  if (entries.length) live.setMessages(prev => [...prev, ...entries]);
}

// Resolves this chat's run id and fetches its Q&A history, appending
// whatever it finds. A separate function (not inlined in the effect) so its
// own guard clauses do not count against the effect callback's complexity.
async function loadQaHistory(
  chatId: string,
  chats: ChatSummary[],
  qaLoadedRef: {current: string | null},
  live: ChatSession,
  isCancelled: () => boolean,
): Promise<void> {
  const runId = chatRunId(chats, chatId);
  if (!runId) return;
  try {
    const rows = await getRunMessages(runId);
    if (!isCancelled()) applyQaRows(chatId, qaLoadedRef, live, rows);
  } catch {
    // Best-effort: the interview transcript above is the load that matters
    // most, so a Q&A fetch failure leaves it showing without its later
    // exchanges rather than failing the whole reopen.
  }
}

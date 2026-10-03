import {useCallback, useEffect, useRef, useState} from 'react';
import type {Interview} from '@/api/runs';
import {
  getRun,
  getInterview,
  getRunMessages,
  isCancelledStatus,
  isDraftStatus,
  type ChatSummary,
  type Run,
  type RunMessage,
} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {type InferredRunSpec} from '../run_spec';
import {type StartedSession} from '../pages/chat_timeline_started_card';
import {useChatHistoryContext} from './chat_history_context';
import {useRunHistoryContext} from './run_history_context';
import {applyInterview} from './chat_session_transcript';
import {readPendingCreateIntent} from './chat_session_create_intent';
import {type LinkedDraftRecovery} from './chat_session_types';
import {
  type LinkedRun,
  type LinkedRunTarget,
  type PendingRunCreatePayload,
  currentLinkedRun,
  recoverySpecForRun,
  recoveryStatus,
  recoverySummary,
} from './chat_linked_run_recovery';
import {
  qaMessagesToEntries,
  runStartAnnouncement,
  type RehydratedAnnouncement,
} from './chat_session_transcript';
import {type useChatSession} from './use_chat_session';

type ChatSession = ReturnType<typeof useChatSession>;

interface RunResolution {
  chatId: string;
  runId: string;
  chat: ChatSummary | undefined;
  interview: Interview | null;
  run: Run;
  recoverySpec?: InferredRunSpec;
}

interface RunResolutionCallbacks {
  cancelled: () => boolean;
  setLinkedRun: (linkedRun: LinkedRun | null) => void;
  setStartedSession: ChatSession['setStartedSession'];
}

async function runForRecovery(
  target: LinkedRunTarget,
  listedRun: Run | undefined,
  refreshStatus: boolean,
): Promise<Run> {
  if (!refreshStatus && listedRun) return listedRun;
  return getRun(target.runId);
}

async function pendingIntentForRun(
  target: LinkedRunTarget,
  run: Run,
): Promise<PendingRunCreatePayload | undefined> {
  if (!isDraftStatus(run.status)) return undefined;
  const intent = await readPendingCreateIntent<PendingRunCreatePayload>(
    target.chatId,
  );
  return intent?.payload;
}

function recoverySpecForStatus(
  target: LinkedRunTarget,
  run: Run,
  intent: PendingRunCreatePayload | undefined,
): InferredRunSpec | undefined {
  if (!isDraftStatus(run.status)) return undefined;
  return recoverySpecForRun(target, run, intent);
}

interface ResolveLinkedRunArgs {
  chatId: string | undefined;
  chats: ChatSummary[];
  history: Run[];
  interview: Interview | null;
  startedSession: StartedSession | null;
  setLinkedRun: (linkedRun: LinkedRun | null) => void;
  setStartedSession: ChatSession['setStartedSession'];
}

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
    id: run?.id ?? String(chat.run_id),
    title: startedTitle(run, chat.challenge),
    at: run?.created_at ?? chat.updated_at,
  };
}

function linkedRunSummary(
  chat: ChatSummary | undefined,
  interview: Interview | null,
  chatId: string,
  runId: string,
  run: Run,
): ChatSummary {
  if (chat) return chat;
  const title = interview ? interview.fields.title : null;
  const challenge = interview ? interview.fields.research_challenge : '';
  const status = interview ? interview.status : 'completed';
  return {
    id: chatId,
    title,
    challenge,
    status,
    run_id: runId,
    created_at: run.created_at,
    updated_at: run.updated_at,
  };
}

function applyResolvedRun(
  resolution: RunResolution,
  callbacks: RunResolutionCallbacks,
): void {
  if (callbacks.cancelled()) return;
  const {chatId, runId, chat, interview, run, recoverySpec} = resolution;
  callbacks.setLinkedRun({
    chatId,
    runId,
    phase: 'ready',
    run,
    recoverySpec,
  });
  if (isDraftStatus(run.status) || isCancelledStatus(run.status)) {
    callbacks.setStartedSession(current =>
      current?.id === runId ? null : current,
    );
    return;
  }
  const summary = linkedRunSummary(chat, interview, chatId, runId, run);
  callbacks.setStartedSession(current =>
    current?.id === runId ? current : resumedSession(summary, run),
  );
}

function loadLinkedRun(
  target: LinkedRunTarget,
  listedRun: Run | undefined,
  refreshStatus: boolean,
  callbacks: RunResolutionCallbacks,
): void {
  void (async () => {
    const run = await runForRecovery(target, listedRun, refreshStatus);
    const intent = await pendingIntentForRun(target, run);
    const recoverySpec = recoverySpecForStatus(target, run, intent);
    applyResolvedRun({...target, run, recoverySpec}, callbacks);
  })().catch(() => {
    // An inaccessible or deleted linked run must not be promoted to a new run.
    if (!callbacks.cancelled()) {
      callbacks.setLinkedRun({...target, phase: 'error'});
    }
  });
}

function linkedRunTarget(args: ResolveLinkedRunArgs): LinkedRunTarget | null {
  if (!args.chatId) return null;
  const chat = args.chats.find(entry => entry.id === args.chatId);
  const runId = linkedRunId(args.interview, chat);
  if (!runId) {
    return null;
  }
  return {chatId: args.chatId, runId, chat, interview: args.interview};
}

function linkedRunId(
  interview: Interview | null,
  chat: ChatSummary | undefined,
): string | null {
  if (interview?.run_id) return interview.run_id;
  return chat?.run_id ?? null;
}

function resolveLinkedRun(
  args: ResolveLinkedRunArgs,
  refreshStatus: boolean,
): () => void {
  const target = linkedRunTarget(args);
  if (!target) {
    args.setLinkedRun(null);
    return () => undefined;
  }
  if (args.startedSession?.id === target.runId) {
    args.setLinkedRun(null);
    return () => undefined;
  }

  let cancelled = false;
  const callbacks = {
    cancelled: () => cancelled,
    setLinkedRun: args.setLinkedRun,
    setStartedSession: args.setStartedSession,
  };
  const listedRun = args.history.find(entry => entry.id === target.runId);
  args.setLinkedRun({...target, phase: 'loading'});
  loadLinkedRun(target, listedRun, refreshStatus, callbacks);
  return () => {
    cancelled = true;
  };
}

function interviewForChat(
  session: ChatSession,
  chatId: string | undefined,
): Interview | null {
  return session.interview?.id === chatId ? session.interview : null;
}

function currentRunId(
  interview: Interview | null,
  chats: ChatSummary[],
  chatId: string | undefined,
): string | null {
  if (interview?.run_id) return interview.run_id;
  return chatRunId(chats, chatId ?? '');
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
): LinkedDraftRecovery {
  const {chats} = useChatHistoryContext();
  const {history} = useRunHistoryContext();
  // The chat this hook has already applied, so a re-render (or the session's
  // own updates) cannot re-fetch and stomp on live state.
  const appliedRef = useRef<string | null>(null);
  // The chat this hook has already fetched Q&A history for -- separate from
  // appliedRef because it depends on the run id, which arrives from the
  // chats list on its own schedule (see the third effect below).
  const qaLoadedRef = useRef<string | null>(null);
  // The reopened run's start announcement, once its messages have loaded.
  // State rather than a ref: the card it belongs on is built by a different
  // effect, and the merge below has to re-run when either side lands.
  const [announcement, setAnnouncement] =
    useState<RehydratedAnnouncement | null>(null);
  const [linkedRun, setLinkedRun] = useState<LinkedRun | null>(null);
  const [lookupRetry, setLookupRetry] = useState(0);
  const retryLinkedRunLookup = useCallback(
    () => setLookupRetry(current => current + 1),
    [],
  );
  const sessionRef = useRef(session);
  sessionRef.current = session;

  useEffect(() => {
    const live = sessionRef.current;
    if (!chatId) {
      // Navigated back out of a chat: leave the workspace as new.
      if (appliedRef.current) live.resetSession();
      appliedRef.current = null;
      qaLoadedRef.current = null;
      setAnnouncement(null);
      return;
    }
    if (alreadyShowing(live, chatId, appliedRef.current)) return;
    // Belongs to the chat being left, not the one being opened.
    setAnnouncement(null);
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

  // Resolve a linked run only after reading its owned status. The interview
  // points at a run as soon as creation commits, while that run may still be
  // a DRAFT whose start request never reached the server.
  useEffect(
    () =>
      resolveLinkedRun(
        {
          chatId,
          chats,
          history,
          interview: interviewForChat(sessionRef.current, chatId),
          startedSession: session.startedSession,
          setLinkedRun,
          setStartedSession: sessionRef.current.setStartedSession,
        },
        lookupRetry > 0,
      ),
    [
      chatId,
      chats,
      history,
      lookupRetry,
      session.interview,
      session.startedSession?.id,
    ],
  );

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
    if (
      !readyToLoadQa(
        chatId,
        qaLoadedRef.current,
        live.interview?.id,
        appliedRef.current,
      )
    ) {
      return;
    }
    let cancelled = false;
    void loadQaHistory(
      chatId,
      chats,
      {qaLoadedRef, live, onAnnouncement: setAnnouncement},
      () => cancelled,
    );
    return () => {
      cancelled = true;
    };
  }, [chatId, chats, session.interview]);

  // The announcement onto the card, once both are in hand. They arrive from
  // two independent fetches in either order -- the chats/runs lists build the
  // card, the run's messages carry its lead-in -- so this waits for the pair
  // rather than the loader trying to patch a card that may not exist yet.
  //
  // Applied only to a card that has no lead-in: returning `current` unchanged
  // once it has one is what stops this effect, which depends on the session
  // it writes to, from re-running on its own output.
  useEffect(() => {
    if (!announcement) return;
    sessionRef.current.setStartedSession(current =>
      current && current.intro === undefined
        ? {...current, ...announcement}
        : current,
    );
  }, [announcement, session.startedSession]);

  const interview = interviewForChat(session, chatId);
  const runId = currentRunId(interview, chats, chatId);
  const currentLinked = currentLinkedRun(
    chatId,
    runId,
    linkedRun,
    session.startedSession,
  );
  return {
    ...recoverySummary(currentLinked),
    status: recoveryStatus(currentLinked),
    retryStatusLookup: retryLinkedRunLookup,
  };
}

// Whether the Q&A rehydration effect above should run for this render: a
// chat is named, it has not already been fetched, and the interview
// transcript for it was *reopened* by this hook (see the effect's own comment
// for why order matters). `chatId` narrows to `string` so the caller need not
// repeat the undefined check.
//
// `appliedFor` is what confines this to reopened tabs. The live session is
// short-circuited by alreadyShowing and so never sets it -- and a tab that
// just started a run already has that exchange on screen, so fetching the
// rows it just wrote appends a second copy of every one of them. That was
// unreachable only while starting a run persisted no messages.
function readyToLoadQa(
  chatId: string | undefined,
  loadedFor: string | null,
  interviewId: string | undefined,
  appliedFor: string | null,
): chatId is string {
  return (
    Boolean(chatId) &&
    loadedFor !== chatId &&
    interviewId === chatId &&
    appliedFor === chatId
  );
}

// This chat's run id per the chats list, if it has one yet.
function chatRunId(chats: ChatSummary[], chatId: string): string | null {
  return chats.find(entry => entry.id === chatId)?.run_id ?? null;
}

// Where a loaded chat's persisted rows are written back to: the session that
// takes the bubbles, the marker saying this chat has been fetched, and the
// caller's sink for the start announcement.
interface QaLoadTarget {
  qaLoadedRef: {current: string | null};
  live: ChatSession;
  onAnnouncement: (announcement: RehydratedAnnouncement) => void;
}

// Marks this chat's Q&A history loaded and applies whatever rows it found (a
// no-op fetch is not an error, just nothing yet to show): the bubbles are
// appended, and the Agent's start announcement is handed to the caller, which
// merges it onto the session card once that card exists.
function applyQaRows(
  chatId: string,
  target: QaLoadTarget,
  rows: RunMessage[],
): void {
  target.qaLoadedRef.current = chatId;
  const entries = qaMessagesToEntries(rows);
  if (entries.length) target.live.setMessages(prev => [...prev, ...entries]);
  const announcement = runStartAnnouncement(rows);
  if (announcement) target.onAnnouncement(announcement);
}

// Resolves this chat's run id and fetches its Q&A history, appending
// whatever it finds. A separate function (not inlined in the effect) so its
// own guard clauses do not count against the effect callback's complexity.
async function loadQaHistory(
  chatId: string,
  chats: ChatSummary[],
  target: QaLoadTarget,
  isCancelled: () => boolean,
): Promise<void> {
  const runId = chatRunId(chats, chatId);
  if (!runId) return;
  try {
    const rows = await getRunMessages(runId);
    if (!isCancelled()) applyQaRows(chatId, target, rows);
  } catch {
    // Best-effort: the interview transcript above is the load that matters
    // most, so a Q&A fetch failure leaves it showing without its later
    // exchanges rather than failing the whole reopen.
  }
}

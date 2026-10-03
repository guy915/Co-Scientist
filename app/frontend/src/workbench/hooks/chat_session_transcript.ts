import type {Dispatch, SetStateAction} from 'react';
import {makePrefixedId} from '@/lib/client_id';
import {DIAGNOSTIC_EVENT} from '../dom_events';
import type {QaSource} from '@/api/runs';
import {type Interview, type InterviewTurn, type RunMessage} from '@/api/runs';
import {interviewToRunSpec} from '../run_spec';
import {type ChatEntry} from '../pages/chat_timeline_bubble';
import {type HandlerDeps} from './use_chat_session';

/**
 * One persisted turn as a timeline bubble.
 *
 * The Agent's reasoning rides along so a turn shows the thinking that
 * produced it exactly as it did while streaming, and the durable turn id
 * rides along so the bubble can be edited or retried in place.
 */
export function turnToEntry(turn: InterviewTurn): ChatEntry {
  const role = turn.role === 'agent' ? 'assistant' : 'user';
  return {
    // Keyed by the turn, not freshly generated: the log is rebuilt from the
    // server after every turn, and a new id each time would remount every
    // bubble on the page (losing its measured collapse state) to redraw text
    // that did not change.
    id: `turn-${turn.id}`,
    role,
    content: turn.content,
    reasoning: turn.reasoning ?? undefined,
    turnId: turn.id,
    // Rides with the bubble exactly as persisted: a fallback-authored turn
    // keeps its marker through every rebuild of the log.
    fallback: turn.fallback || undefined,
    created_at: turn.created_at,
  };
}

/**
 * Splits an interview's transcript for display: a completed interview's
 * closing Agent turn becomes the plan card's lead-in rather than a bubble of
 * its own, so the conversation reads as one response instead of a bubble
 * plus a card.
 */
export function splitTranscript(interview: Interview): {
  entries: ChatEntry[];
  closing: InterviewTurn | null;
} {
  const turns = [...interview.turns];
  const last = turns[turns.length - 1];
  const closing =
    interview.status === 'completed' && last?.role === 'agent' ? last : null;
  if (closing) turns.pop();
  return {entries: turns.map(turnToEntry), closing};
}

/** The session state an interview snapshot is rendered into. */
export interface TranscriptSink extends Pick<
  HandlerDeps,
  'setInterview' | 'setDraft' | 'setConfirmed' | 'stageDraftSpec'
> {
  // Deliberately wider than HandlerDeps.setMessages: rendering a snapshot
  // replaces the whole log with plain entries, so the sink accepts any
  // replacement setter and must not require the session's stateful dispatch.
  // Do not narrow this to Dispatch<SetStateAction<ChatEntry[]>>.
  setMessages: (entries: ChatEntry[]) => void;
}

/**
 * Renders a resolved interview into the session: its transcript, and the plan
 * it derived once it completes.
 *
 * The server's copy is the whole conversation, so this replaces the message
 * log rather than appending to it. That is what lets a revision (an edited
 * prompt, a retried answer) drop the turns it invalidated: they are simply
 * absent from the snapshot that comes back, and every surviving bubble
 * carries the durable turn id it can be revised by.
 *
 * An interview that is *not* complete cannot leave a plan on screen. Staging
 * one is the completed branch's job, so any card left over from a derivation
 * the scientist has since withdrawn is cleared here.
 */
export function applyInterview(
  sink: TranscriptSink,
  interview: Interview,
): void {
  const {entries, closing} = splitTranscript(interview);
  sink.setMessages(entries);
  sink.setInterview(interview);
  if (closing) {
    const intro = {
      message: closing.content,
      reasoning: closing.reasoning ?? undefined,
      turnId: closing.id,
      // The closing turn becomes the plan card's lead-in instead of a
      // bubble, so its fallback marker rides with it there.
      fallback: closing.fallback || undefined,
    };
    // A chat that already started a run has no plan left to edit. Staging
    // one anyway put Start research live beside a card saying the run was
    // under way -- one click from a second run on the same goal. The
    // server's own answer is used rather than the run the workspace may or
    // may not have looked up yet, so reopening cannot depend on which of
    // the two loads lands first. Editing a settled plan is still offered,
    // by the confirmed card's own Edit, which stages a draft deliberately.
    if (interview.run_id) {
      sink.setDraft(null);
      sink.setConfirmed({
        spec: interviewToRunSpec(interview),
        createdAt: closing.created_at,
        intro: intro.message,
        reasoning: intro.reasoning,
        turnId: intro.turnId,
        fallback: intro.fallback,
      });
      return;
    }
    sink.stageDraftSpec(
      interviewToRunSpec(interview),
      closing.created_at,
      intro,
    );
    return;
  }
  sink.setDraft(null);
  sink.setConfirmed(null);
}

// Converts a run's persisted message rows (GET /messages) into the pieces a
// reopened chat rebuilds itself from: the bubbles for its Q&A exchanges and
// its start request, and the Agent's start announcement, which is not a
// bubble at all but the session card's lead-in. Interview turns above use
// their own durable turn ids and reasoning.

/**
 * The Agent's answer to the scientist's start request, as it is put back on
 * the session card (see run_start_announcement.py for the rows it comes
 * from). `at` is the reply's own timestamp, which is what re-anchors the card
 * *below* the request that produced it -- the run was created first, so the
 * run's own creation time would sort the card above its own prompt.
 */
export interface RehydratedAnnouncement {
  intro: string;
  reasoning?: string;
  at: number;
}

/** A persisted row's sender, as a chat bubble role. */
function qaRole(sender: RunMessage['sender']): ChatEntry['role'] {
  return sender === 'user' ? 'user' : 'assistant';
}

/** One persisted row as a timeline bubble. */
function rowToEntry(row: RunMessage): ChatEntry {
  return {
    id: `qa-${row.id}`,
    role: qaRole(row.sender),
    content: row.content,
    reasoning: row.meta?.reasoning,
    sources: row.meta?.sources,
    created_at: row.created_at,
  };
}

// Whether a row belongs in the timeline as a bubble of its own: every Q&A
// row, plus the scientist's own start request. The Agent's reply to that
// request is deliberately absent -- it is the card's lead-in, exactly as a
// completed interview's closing turn is the plan card's (see
// chat_session_transcript.ts::splitTranscript).
function isBubbleRow(row: RunMessage): boolean {
  if (row.kind === 'qa') return true;
  return row.kind === 'start' && row.sender === 'user';
}

/**
 * Builds the Q&A bubbles for one run, in the order the rows arrived --
 * matching the shape a live ask already produces (see
 * chat_session_handlers_qa.ts), so a reload renders identically to a live
 * turn. Callers pass the full `GET /messages` result; steering rows are
 * dropped, since the same endpoint returns those too.
 */
export function qaMessagesToEntries(rows: RunMessage[]): ChatEntry[] {
  return rows.filter(isBubbleRow).map(rowToEntry);
}

/**
 * Finds the Agent's start announcement among a run's persisted rows.
 *
 * The *first* such reply, not the last: a retried start, or the same chat
 * open in two tabs, can leave more than one, and the card has one lead-in.
 * Null for a run started before the announcement existed, which is what
 * leaves the card on its standby copy.
 */
export function runStartAnnouncement(
  rows: RunMessage[],
): RehydratedAnnouncement | null {
  const reply = rows.find(
    row => row.kind === 'start' && row.sender === 'system',
  );
  if (!reply) return null;
  return {
    intro: reply.content,
    reasoning: reply.meta?.reasoning,
    at: reply.created_at,
  };
}

/** The chat session's diagnostic-log categories. */
export type DiagnosticStage = 'LIFECYCLE' | 'CHAT';

/**
 * Fires a fire-and-forget diagnostic line for the shell's Logs popover
 * (DiagnosticsControl in layout_diagnostics.tsx listens for this event); a
 * window event keeps the chat session decoupled from the shell component.
 */
export function emitDiagnosticEvent({
  stage,
  runId,
  level = 'info',
  payload = {},
}: {
  stage: DiagnosticStage;
  /**
   * Real run id, when one exists. Deliberately not a title: this is
   * persisted as the record's run_id and served over the logs API, so
   * anything goal-derived here would publish research content.
   */
  runId?: string;
  // The persisted log has no "success" band — the levels are Python's, so
  // an emitted success was only ever stored (and counted) as info.
  level?: 'info' | 'warning' | 'error';
  payload?: Record<string, unknown>;
}) {
  window.dispatchEvent(
    new CustomEvent(DIAGNOSTIC_EVENT, {
      detail: {stage, runId, level, payload},
    }),
  );
}

/** One appended chat bubble, as its callers describe it. */
export interface NewChatMessage {
  role: 'assistant' | 'user';
  content: string;
  /** The Agent's chain of thought for this turn, when it produced one. */
  reasoning?: string;
  /** Epoch seconds; defaults to now. */
  createdAt?: number;
  /** A run Q&A answer's evidence manifest; see `ChatEntry.sources`. */
  sources?: QaSource[];
}

/**
 * Appends a chat bubble; timestamps are epoch seconds (matching the API's
 * created_at convention) and returned so callers can order follow-up entries
 * relative to this one. Takes `setMessages` as an argument instead of closing
 * over hook state so every handler that appends a message can share it without
 * each needing its own copy.
 */
export function appendChatMessage(
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>,
  message: NewChatMessage,
): number {
  const createdAt = message.createdAt ?? Date.now() / 1000;
  setMessages(prev => [
    ...prev,
    {
      id: makePrefixedId(message.role),
      role: message.role,
      content: message.content,
      reasoning: message.reasoning,
      sources: message.sources,
      created_at: createdAt,
    },
  ]);
  return createdAt;
}

/**
 * Wraps a ref holding the latest `HandlerDeps` bag in an object whose
 * enumerable getters delegate to `ref.current`. buildChatHandlers can then be
 * called ONCE (stable handler identities across renders) while every handler
 * — including spreads like `{...handlerDeps}` — still reads the current
 * render's state at call time. The key set is fixed by the initial bag, which
 * is fine: HandlerDeps is a closed interface.
 */
export function liveHandlerDeps<T extends object>(ref: {current: T}): T {
  const live = {} as T;
  for (const key of Object.keys(ref.current) as (keyof T)[]) {
    Object.defineProperty(live, key, {
      enumerable: true,
      get: () => ref.current[key],
    });
  }
  return live;
}

// True for the DOMException a fetch (or its SSE body read) rejects with
// once its AbortSignal fires -- the Stop control's own doing, never a
// provider or network failure. Checked by name rather than
// `instanceof Error`: a DOMException is not guaranteed to be one.
export function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as {name?: unknown}).name === 'AbortError'
  );
}

// Starts (and records) the AbortController for one turn, so the composer's
// Stop control -- which only holds the deps bag, not this call's local
// state -- can reach it via `turnAbortRef`.
export function beginTurnAbort(
  deps: Pick<HandlerDeps, 'turnAbortRef'>,
): AbortSignal {
  const controller = new AbortController();
  deps.turnAbortRef.current = controller;
  return controller.signal;
}

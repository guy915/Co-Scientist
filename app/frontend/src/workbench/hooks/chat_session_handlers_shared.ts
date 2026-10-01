import {getInterview, type Interview} from '@/api/runs';
import {applyInterview, type TranscriptSink} from './chat_session_transcript';
import {emitDiagnosticEvent} from './chat_session_helpers';
import {type HandlerDeps} from './chat_session_types';

// Shared by chat_session_handlers.ts (the composer submit path) and
// chat_session_handlers_revise.ts (edit/retry): what a turn's outcome
// means for the session, and how a stopped one is told apart from a
// failed one. Split out so neither of those two files imports from the
// other.

// Applies the Agent's reply for one interview turn to the chat log.
//
// The server's interview is the whole conversation, not a delta, so the log
// is rebuilt from it rather than appended to. That is what gives every bubble
// the durable turn id an edit or a retry addresses, and it means a turn that
// removed earlier turns (a revision) needs no special handling here: they are
// simply absent from the snapshot that came back.
export function applyAgentTurn(updated: Interview, deps: TranscriptSink): void {
  applyInterview(deps, updated);
  emitDiagnosticEvent(
    updated.status === 'completed'
      ? {
          stage: 'LIFECYCLE',
          payload: {event: 'interview_completed', interview_id: updated.id},
        }
      : {
          stage: 'CHAT',
          payload: {event: 'interview_advanced', interview_id: updated.id},
        },
  );
}

// User-facing message for a failed interview turn.
export function describeSubmitError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The Agent could not continue the interview.';
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

/**
 * Ends the turn in flight: drops the live channels and lowers the awaiting
 * flag together.
 *
 * The streamed reasoning and reply belong to the turn that produced them.
 * Left behind after it resolved, they were re-shown whole the next time
 * anything raised `isAwaitingAgent` -- clicking Start research put the
 * interview's closing message back on screen as a bare bubble underneath the
 * plan it had just produced. Clearing them here, in the same place the flag
 * drops, is what keeps the two from ever disagreeing.
 */
export function settleTurn(
  deps: Pick<
    HandlerDeps,
    'setIsAwaitingAgent' | 'setAgentReasoning' | 'setAgentDraft'
  >,
): void {
  deps.setAgentReasoning('');
  deps.setAgentDraft('');
  deps.setIsAwaitingAgent(false);
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

// Recovers from a stopped turn: the streamed draft never persisted (see
// interviews.stream._advance_stream), so it is dropped, then the session
// resyncs from the server -- the sole source of truth for what a stopped
// call actually wrote, and how the client learns the id of the scientist's
// own turn the route persisted before the stream opened. `interviewId` is
// undefined only when the stopped call was itself the interview's own
// creation, since its id arrives with the closing frame the turn never
// reached; the caller handles that case separately.
export async function recoverFromStoppedTurn(
  deps: TranscriptSink &
    Pick<HandlerDeps, 'setAgentReasoning' | 'setAgentDraft'>,
  interviewId: string | undefined,
): Promise<void> {
  deps.setAgentReasoning('');
  deps.setAgentDraft('');
  if (!interviewId) return;
  const updated = await getInterview(interviewId);
  applyInterview(deps, updated);
}

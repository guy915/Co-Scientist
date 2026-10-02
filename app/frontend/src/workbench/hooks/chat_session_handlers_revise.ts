import {
  editInterviewTurn,
  retryInterviewTurn,
  type Interview,
  type InterviewSinks,
} from '@/api/runs';
import {type ChatEntry} from '../pages/chat_timeline_bubble';
import {announceChatsChanged} from './chat_history_context';
import {emitDiagnosticEvent} from './chat_session_helpers';
import {
  applyAgentTurn,
  beginTurnAbort,
  describeSubmitError,
  isAbortError,
  recoverFromStoppedTurn,
  settleTurn,
} from './chat_session_handlers_shared';
import {type HandlerDeps} from './chat_session_types';

/**
 * Runs one interview revision and rebuilds the session from the conversation
 * it produced.
 *
 * Shared by editing a prompt and retrying an answer because both are the same
 * transaction: rewind the transcript to the turn in question, let the Agent
 * answer again, and adopt whatever conversation comes back. Neither is an
 * append, which is why neither can be expressed as another composer turn.
 */
async function reviseInterviewTurn(
  deps: HandlerDeps,
  revise: (sinks: InterviewSinks, signal: AbortSignal) => Promise<Interview>,
): Promise<void> {
  deps.setError(null);
  deps.setToast(null);
  deps.setIsAwaitingAgent(true);
  deps.setAgentReasoning('');
  deps.setAgentDraft('');
  const signal = beginTurnAbort(deps);
  try {
    const updated = await revise(
      {
        onReasoning: fragment =>
          deps.setAgentReasoning(current => current + fragment),
        onProse: fragment => deps.setAgentDraft(current => current + fragment),
      },
      signal,
    );
    applyAgentTurn(updated, deps);
    announceChatsChanged();
  } catch (error) {
    if (isAbortError(error)) {
      await recoverFromStoppedTurn(deps, deps.interview?.id);
    } else {
      deps.setError(describeSubmitError(error));
    }
  } finally {
    deps.turnAbortRef.current = null;
    settleTurn(deps);
  }
}

// The durable turn a revision targets, or null when there is nothing to
// revise: an optimistic bubble, a locally-authored line — or a session that
// has already started a run. A started run locks the transcript it was
// created from: the timeline hides edit/retry from that moment, and this
// check (which both callers run before their optimistic truncation) keeps
// the handlers aligned with it.
function revisableTurn(
  deps: HandlerDeps,
  message: ChatEntry,
): {interviewId: string; turnId: number} | null {
  if (deps.startedSession) return null;
  const interviewId = deps.interview?.id;
  if (!interviewId || !message.turnId) return null;
  return {interviewId, turnId: message.turnId};
}

// Drops the turns a revision invalidates so the transcript reads as the
// correction immediately rather than after the round trip. `content` replaces
// the target message (an edit); omitting it drops the target too (a retry).
function truncateAtMessage(
  messages: ChatEntry[],
  target: ChatEntry,
  content?: string,
): ChatEntry[] {
  const index = messages.findIndex(entry => entry.id === target.id);
  if (index < 0) return messages;
  const kept = messages.slice(0, index);
  return content === undefined ? kept : [...kept, {...target, content}];
}

// Rewrites a scientist prompt where it stands and re-answers from there.
export function editUserMessage(
  deps: HandlerDeps,
  message: ChatEntry,
  content: string,
): void {
  const target = revisableTurn(deps, message);
  const text = content.trim();
  if (!target || !text) return;
  deps.setMessages(current => truncateAtMessage(current, message, text));
  void reviseInterviewTurn(deps, (sinks, signal) =>
    editInterviewTurn(target.interviewId, target.turnId, text, sinks, signal),
  );
  emitDiagnosticEvent({stage: 'CHAT', payload: {event: 'prompt_edited'}});
}

// Discards an Agent answer and asks for another in its place.
export function retryAssistantMessage(
  deps: HandlerDeps,
  message: ChatEntry,
): void {
  const target = revisableTurn(deps, message);
  if (!target) return;
  deps.setMessages(current => truncateAtMessage(current, message));
  void reviseInterviewTurn(deps, (sinks, signal) =>
    retryInterviewTurn(target.interviewId, target.turnId, sinks, signal),
  );
  emitDiagnosticEvent({stage: 'CHAT', payload: {event: 'response_retried'}});
}

// The durable turn a plan re-derivation targets, or null when the staged
// plan carries no turn to retry.
function draftRevisionTarget(deps: HandlerDeps): {
  interviewId: string;
  turnId: number;
} | null {
  const interviewId = deps.interview?.id;
  const turnId = deps.draft?.turnId;
  if (!interviewId || !turnId) return null;
  return {interviewId, turnId};
}

// Re-derives the staged plan by retrying the Agent turn that produced it.
// The plan is that turn's answer, so "retry" here means the same thing it
// means on any other response; re-staging the spec already in hand looked
// like a dead control because nothing about it could change.
export function retryDraftSpec(deps: HandlerDeps): void {
  // Locked once a run has started; see revisableTurn. Rehydration can leave
  // a draft staged alongside a started session, so the check is not redundant
  // with the draft being null.
  if (deps.startedSession) return;
  const target = draftRevisionTarget(deps);
  if (!target) return;
  deps.setDraft(null);
  void reviseInterviewTurn(deps, (sinks, signal) =>
    retryInterviewTurn(target.interviewId, target.turnId, sinks, signal),
  );
  emitDiagnosticEvent({stage: 'CHAT', payload: {event: 'plan_retried'}});
}

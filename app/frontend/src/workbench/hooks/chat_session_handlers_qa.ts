import {type FormEvent} from 'react';
import {askRunQuestion, type QaSource} from '@/api/runs';
import {appendChatMessage} from './chat_session_helpers';
import {beginTurnAbort, isAbortError} from './chat_session_handlers_shared';
import {type HandlerDeps} from './chat_session_types';

// The composer's *only* submit path once a run has started (see the
// routing in chat_session_handlers.ts's buildChatHandlers). The durable
// interview is completed and closed server-side the moment a run starts;
// posting another turn to it is the exact bug the composer lock existed to
// stop (audit row A17). Asking the run's own Q&A endpoint instead keeps the
// composer live without ever reaching an interview endpoint again.

// The handler-bag slice a Q&A submit reads, plus the submit event itself.
// Mirrors SubmitComposerDeps in chat_session_handlers.ts, but never touches
// `interview` -- a question is asked of the run, not the closed interview.
type AskComposerDeps = Pick<
  HandlerDeps,
  | 'input'
  | 'startedSession'
  | 'audience'
  | 'setInput'
  | 'setError'
  | 'setToast'
  | 'setMessages'
  | 'setIsStarting'
  | 'setIsAwaitingAgent'
  | 'setAgentDraft'
  | 'turnAbortRef'
> & {e: FormEvent<HTMLFormElement>};

// Clears the composer for a new question; returns the trimmed text, or
// null when there is nothing to ask.
function beginAskTurn(deps: AskComposerDeps): string | null {
  const text = deps.input.trim();
  if (!text) return null;
  deps.setInput('');
  deps.setError(null);
  deps.setToast(null);
  return text;
}

// User-facing message for a failed question. Kept apart from
// describeSubmitError (chat_session_handlers_shared.ts), whose fallback
// text names the interview -- a run question never reaches that endpoint.
function describeAskError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The Agent could not answer the question.';
}

// The sinks passed to askRunQuestion: accumulates the answer locally (for
// the bubble persisted on success) while also feeding the live-growing
// draft the timeline renders as chunks arrive.
function buildAskSinks(deps: Pick<AskComposerDeps, 'setAgentDraft'>) {
  let answer = '';
  let sources: QaSource[] = [];
  return {
    sinks: {
      onSources: (found: QaSource[]) => {
        sources = found;
      },
      onChunk: (fragment: string) => {
        answer += fragment;
        deps.setAgentDraft(current => current + fragment);
      },
    },
    result: () => ({answer, sources}),
  };
}

// The round trip itself, once there is a run and a question to ask it: post
// the optimistic bubble, stream the answer, and settle either outcome.
// Split out of submitRunQuestion so its own guard clauses stay under the
// complexity ceiling.
//
// A stopped turn drops the partial answer rather than resyncing: unlike an
// interview turn, nothing is persisted server-side until the stream
// completes (see qa.py's `_framed_answer`), so there is nothing to recover
// -- the abort itself is enough.
async function runAskRequest(
  deps: AskComposerDeps,
  runId: string,
  text: string,
): Promise<void> {
  appendChatMessage(deps.setMessages, {role: 'user', content: text});
  // Mirrors the interview submit's own setIsStarting(true): Composer's
  // `busy` prop is what blocks a second Enter/Send while a turn is in
  // flight. Without it, a question submitted mid-stream orphans the first
  // turn's AbortController (Stop only reaches the second) and both
  // streams write into the one shared agentDraft, garbling the answer.
  deps.setIsStarting(true);
  deps.setIsAwaitingAgent(true);
  deps.setAgentDraft('');
  const {sinks, result} = buildAskSinks(deps);
  const signal = beginTurnAbort(deps);
  try {
    await askRunQuestion(
      runId,
      text,
      sinks,
      deps.audience ?? undefined,
      signal,
    );
    const {answer, sources} = result();
    appendChatMessage(deps.setMessages, {
      role: 'assistant',
      content: answer,
      sources,
    });
  } catch (error) {
    if (!isAbortError(error)) deps.setError(describeAskError(error));
  } finally {
    deps.turnAbortRef.current = null;
    deps.setIsStarting(false);
    deps.setIsAwaitingAgent(false);
    deps.setAgentDraft('');
  }
}

/**
 * Asks the started run's grounded Q&A endpoint one question, streaming the
 * answer into the timeline as it arrives.
 */
export async function submitRunQuestion(deps: AskComposerDeps): Promise<void> {
  deps.e.preventDefault();
  const runId = deps.startedSession?.id;
  if (!runId) return;
  const text = beginAskTurn(deps);
  if (text === null) return;
  await runAskRequest(deps, runId, text);
}

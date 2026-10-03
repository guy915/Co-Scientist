import {beginTurnAbort, isAbortError} from './chat_session_transcript';
import {
  appendChatMessage,
  emitDiagnosticEvent,
} from './chat_session_transcript';
import type {FormEvent} from 'react';
import {
  addInterviewTurn,
  createInterview,
  stageDocument,
  type Interview,
  type InterviewSinks,
  type StagedDocument,
  getInterview,
  askRunQuestion,
  type QaSource,
  editInterviewTurn,
  retryInterviewTurn,
} from '@/api/runs';
import {copyText} from '@/lib/clipboard';
import {announceChatsChanged} from './history_context';
import {
  type ChatSessionDeps,
  type HandlerDeps,
  type ComposerLog,
  type RunSpecLifecycle,
} from './use_chat_session';
import {promoteDraftToRun} from './chat_session_start_run';
import type {ChatEntry} from '../pages/chat_timeline_bubble';
import {applyInterview, type TranscriptSink} from './chat_session_transcript';

// The handler-bag slice a composer submit reads, plus the two values only the
// submit event itself supplies. Projected off HandlerDeps rather than
// restated, so a field that changes shape there cannot drift out of sync here.
type SubmitComposerDeps = Pick<
  HandlerDeps,
  | 'input'
  | 'interview'
  | 'startedSession'
  | 'setInput'
  | 'setError'
  | 'setToast'
  | 'setMessages'
  | 'setInterview'
  | 'onChatStarted'
  | 'setIsStarting'
  | 'setIsAwaitingAgent'
  | 'setAgentReasoning'
  | 'setAgentDraft'
  | 'turnAbortRef'
  | 'setPendingAttachments'
  | 'setDraft'
  | 'setConfirmed'
  | 'stageDraftSpec'
  | 'clearSessionState'
  | 'reloadHistory'
> & {
  files: File[];
  /**
   * The turn's text when it did not come from the composer -- the answer
   * composed from the question chooser's option cards. Given, it is what is
   * sent and the composer's own contents are left alone, so a half-written
   * message survives answering a question by clicking.
   */
  answer?: string;
};

// Clears the composer for a new turn; returns the trimmed text, or null
// when there is nothing to submit.
//
// A clicked answer (`answer`) leaves the composer's contents where they
// are: it is not what is being sent, and wiping it would discard a message
// the scientist was part-way through writing.
function beginComposerTurn(deps: SubmitComposerDeps): string | null {
  const text = (deps.answer ?? deps.input).trim();
  if (!text) return null;
  if (deps.answer === undefined) deps.setInput('');
  deps.setError(null);
  deps.setToast(null);
  return text;
}

// Uploads the files attached to this turn and records them on the session.
//
// The upload happens here, with the turn, rather than after a run has been
// created: the Agent reads the staged text while deriving this very turn,
// which is what makes attaching a paper shape the conversation it was
// attached to. The ids are also what creating the run carries in later.
async function stageTurnFiles(
  deps: SubmitComposerDeps,
): Promise<StagedDocument[]> {
  if (!deps.files.length) return [];
  const staged = await Promise.all(deps.files.map(file => stageDocument(file)));
  deps.setPendingAttachments(current => [...current, ...staged]);
  return staged;
}

// Advances the durable interview by one turn: continues it when one is
// already in progress, else starts a fresh one.
function startInterviewTurn(
  deps: Pick<SubmitComposerDeps, 'interview'>,
  text: string,
  sinks: InterviewSinks,
  documentIds: string[],
  signal: AbortSignal,
): Promise<Interview> {
  if (deps.interview) {
    return addInterviewTurn(
      deps.interview.id,
      text,
      sinks,
      documentIds,
      signal,
    );
  }
  return createInterview(text, sinks, documentIds, signal);
}

// What submitComposerMessage's catch does with the round trip's outcome: a
// real failure shows the error banner; a stop the scientist asked for
// (AbortError) never does. Split out to keep the caller under the
// complexity ceiling.
async function handleSubmitOutcome(
  deps: SubmitComposerDeps,
  error: unknown,
  isFirstTurn: boolean,
  text: string,
): Promise<void> {
  if (!isAbortError(error)) {
    deps.setError(describeSubmitError(error));
    return;
  }
  if (isFirstTurn) {
    // The interview id only arrives with the closing frame, so a stopped
    // creation leaves nothing to resync against -- restore the composer and
    // let the sidebar pick up the abandoned chat instead. Nothing is lost
    // server-side; there is simply no id here to reach it by yet.
    clearConversation(deps, text);
    await deps.reloadHistory();
    return;
  }
  await recoverFromStoppedTurn(deps, deps.interview?.id);
}

// Composer submit advances the durable Agent interview. The browser never
// derives scientific setup fields from keywords; only the persisted model
// response can complete the setup and produce a runnable specification.
async function submitComposerMessage(deps: SubmitComposerDeps): Promise<void> {
  // A started run consumed the interview: the server completed it when the
  // run was created, so it rejects further turns. buildChatHandlers routes
  // handleSubmit to submitRunQuestion instead the moment startedSession is
  // set, so this function is never called in that state -- this guard is
  // the second line of defense against ever reaching an interview endpoint
  // post-start (audit row A17), not the primary one.
  if (deps.startedSession) return;
  const text = beginComposerTurn(deps);
  if (text === null) return;

  // Optimistic: the prompt is on screen before the round trip, and the
  // rebuild below replaces it with the durable turn it became.
  appendChatMessage(deps.setMessages, {role: 'user', content: text});
  deps.setIsStarting(true);
  deps.setIsAwaitingAgent(true);
  // Each turn shows only its own thinking and its own reply in progress,
  // so drop the previous turn's.
  deps.setAgentReasoning('');
  deps.setAgentDraft('');
  const sinks = {
    onReasoning: (fragment: string) =>
      deps.setAgentReasoning(current => current + fragment),
    onProse: (fragment: string) =>
      deps.setAgentDraft(current => current + fragment),
  };
  const isFirstTurn = deps.interview === null;
  const signal = beginTurnAbort(deps);
  try {
    const staged = await stageTurnFiles(deps);
    const updated = await startInterviewTurn(
      deps,
      text,
      sinks,
      staged.map(document => document.id),
      signal,
    );
    deps.setInterview(updated);
    // The chat exists server-side from here on: list it in the rail, and on
    // its first turn put its id in the URL so reloading or reopening it
    // returns to this conversation rather than a blank workspace.
    announceChatsChanged();
    if (isFirstTurn) deps.onChatStarted(updated.id);
    applyAgentTurn(updated, deps);
  } catch (error) {
    await handleSubmitOutcome(deps, error, isFirstTurn, text);
  } finally {
    deps.turnAbortRef.current = null;
    deps.setIsStarting(false);
    settleTurn(deps);
  }
}

/** The session slice a "back to an empty conversation" transition writes. */
type ClearConversationDeps = Pick<
  HandlerDeps,
  'setInput' | 'clearSessionState' | 'setMessages' | 'setError'
>;

// Empties the whole conversation -- every spec/session stage, the message log,
// and any error -- leaving the composer holding `input`. Both ways back to a
// blank workspace (cancelling a draft, starting a new chat from a copied
// prompt) are this same wipe; only the composer's parting text and the toast
// they leave behind differ.
function clearConversation(deps: ClearConversationDeps, input: string): void {
  deps.clearSessionState();
  deps.setMessages([]);
  deps.setError(null);
  deps.setInput(input);
}

// Cancels the draft and clears the whole conversation (not just the spec),
// returning the workspace to its empty state. Takes its dependencies as
// arguments instead of closing over hook state.
function cancelDraftSpec(
  deps: ClearConversationDeps & Pick<HandlerDeps, 'setToast'>,
) {
  clearConversation(deps, '');
  deps.setToast('The session was canceled');
  emitDiagnosticEvent({
    stage: 'LIFECYCLE',
    payload: {event: 'draft_cancelled'},
  });
}

// Copies a message's prompt text and offers a "Start new chat" toast action
// that clears the session and prefills the composer with it. Takes its
// dependencies as arguments instead of closing over hook state.
type CopyMessagePromptDeps = ClearConversationDeps &
  Pick<HandlerDeps, 'setToast' | 'focusComposer'> & {message: ChatEntry};

async function copyMessagePrompt({
  message,
  setInput,
  clearSessionState,
  setMessages,
  setError,
  setToast,
  focusComposer,
}: CopyMessagePromptDeps): Promise<void> {
  const promptText = message.content;
  await copyText(promptText);
  // Named apart from the deps bag so the long-lived toast action below holds
  // only the four setters it uses, rather than pinning the whole handler bag
  // (and with it the staged attachment Files) for as long as the toast shows.
  const clear = {setInput, clearSessionState, setMessages, setError};
  // Copy is a pure utility (matching the reference): it does not stage a
  // draft. The toast offers "Start new chat", which clears the session and
  // prefills the composer with the copied prompt.
  setToast({
    message: 'Prompt copied',
    action: {
      label: 'Start new chat',
      onClick: () => {
        clearConversation(clear, promptText);
        setToast(null);
        focusComposer();
      },
    },
  });
  emitDiagnosticEvent({
    stage: 'CHAT',
    payload: {event: 'prompt_copied'},
  });
}

// Cancels the turn currently in flight, if any. A no-op once the turn has
// already resolved -- `turnAbortRef` is cleared in the same `finally` that
// clears `isAwaitingAgent`, so there is never a stale controller to abort
// by mistake.
function stopTurn(deps: Pick<HandlerDeps, 'turnAbortRef'>): void {
  deps.turnAbortRef.current?.abort();
}

/**
 * Builds the full wrapped-handler set from a `handlerDeps` bag: each handler
 * below either forwards to one of the module-level functions above (or from
 * chat_session_handlers.ts) or closes directly over the one or two
 * deps it needs. Takes no hooks itself (plain function, not a sub-hook), so
 * it can be called unconditionally from anywhere in useChatSession's body.
 *
 * Every handler reads `handlerDeps` properties at CALL time, never at build
 * time: useChatSession passes a live view over a ref (see liveHandlerDeps),
 * so the handler set is built once with stable identities while still seeing
 * the current render's state. Do not destructure the bag up front.
 */
export function buildChatHandlers(handlerDeps: HandlerDeps) {
  return {
    handleRetryMessage: (message: ChatEntry) =>
      retryAssistantMessage(handlerDeps, message),
    handleEditMessage: (message: ChatEntry, content: string) =>
      editUserMessage(handlerDeps, message, content),
    handleCopyRequest: (message: ChatEntry) =>
      copyMessagePrompt({message, ...handlerDeps}),
    handleRetryDraftSpec: () => retryDraftSpec(handlerDeps),
    handleCancelDraftSpec: () => cancelDraftSpec(handlerDeps),
    // A started run's interview is closed server-side, so submit routes to
    // the run's own Q&A endpoint instead of ever posting another interview
    // turn (A17). Read at call time (handlerDeps is the live view over the
    // latest render's state -- see liveHandlerDeps), so this cannot drift
    // behind a stale render.
    handleSubmit: (e: FormEvent<HTMLFormElement>, files: File[] = []) => {
      if (handlerDeps.startedSession) {
        return submitRunQuestion({e, ...handlerDeps});
      }
      // Prevented here rather than inside submitComposerMessage, which is
      // also reached by handleAnswerQuestions below -- an answer clicked in
      // the question chooser has no form submission to prevent.
      e.preventDefault();
      return submitComposerMessage({files, ...handlerDeps});
    },
    // An answer assembled from the question chooser's option cards. It
    // takes the same path a typed answer takes -- one ordinary interview
    // turn -- so the Agent reads the conversation it would have read had
    // the scientist written the answer out.
    handleAnswerQuestions: (answer: string) =>
      submitComposerMessage({files: [], answer, ...handlerDeps}),
    handleStartRun: () => promoteDraftToRun(handlerDeps),
    handleStop: () => stopTurn(handlerDeps),
  };
}

/**
 * Assembles the deps bag every module-level handler function reads from, out
 * of the two sub-hooks' state plus the view-layer collaborators. Takes the
 * sub-hooks' return values as arguments instead of closing over hook state (it
 * calls no hooks itself).
 */
export function toHandlerDeps(
  lifecycle: RunSpecLifecycle,
  composer: ComposerLog,
  view: ChatSessionDeps,
): HandlerDeps {
  return {
    input: composer.input,
    setInput: composer.setInput,
    draft: lifecycle.draft,
    interview: lifecycle.interview,
    startedSession: lifecycle.startedSession,
    setInterview: lifecycle.setInterview,
    setDraft: lifecycle.setDraft,
    setConfirmed: lifecycle.setConfirmed,
    setStartedSession: lifecycle.setStartedSession,
    setIsStarting: composer.setIsStarting,
    setIsAwaitingAgent: composer.setIsAwaitingAgent,
    setAgentReasoning: composer.setAgentReasoning,
    setAgentDraft: composer.setAgentDraft,
    turnAbortRef: composer.turnAbortRef,
    setMessages: composer.setMessages,
    setError: composer.setError,
    pendingAttachments: composer.pendingAttachments,
    setPendingAttachments: composer.setPendingAttachments,
    setToast: view.setToast,
    clearSessionState: lifecycle.clearSessionState,
    stageDraftSpec: lifecycle.stageDraftSpec,
    focusComposer: view.focusComposer,
    reloadHistory: view.reloadHistory,
    onChatStarted: view.onChatStarted,
    pubmedEnabled: view.pubmedEnabled,
    webSearchEnabled: view.webSearchEnabled,
  };
}

// Shared by chat_session_handlers.ts (the composer submit path) and
// chat_session_handlers.ts (edit/retry): what a turn's outcome
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
  | 'setInput'
  | 'setError'
  | 'setToast'
  | 'setMessages'
  | 'setIsStarting'
  | 'setIsAwaitingAgent'
  | 'setAgentReasoning'
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
// describeSubmitError (chat_session_handlers.ts), whose fallback
// text names the interview -- a run question never reaches that endpoint.
function describeAskError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The Agent could not answer the question.';
}

// The sinks passed to askRunQuestion: accumulates the answer and its
// reasoning locally (for the bubble persisted on success) while also
// feeding the live-growing draft the timeline renders as fragments arrive.
function buildAskSinks(
  deps: Pick<AskComposerDeps, 'setAgentReasoning' | 'setAgentDraft'>,
) {
  let answer = '';
  let reasoning = '';
  let sources: QaSource[] = [];
  return {
    sinks: {
      onSources: (found: QaSource[]) => {
        sources = found;
      },
      onReasoning: (fragment: string) => {
        reasoning += fragment;
        deps.setAgentReasoning(current => current + fragment);
      },
      onChunk: (fragment: string) => {
        answer += fragment;
        deps.setAgentDraft(current => current + fragment);
      },
    },
    result: () => ({answer, reasoning, sources}),
  };
}

// The round trip itself, once there is a run and a question to ask it: post
// the optimistic bubble, stream the answer, and settle either outcome.
// Split out of submitRunQuestion so its own guard clauses stay under the
// complexity ceiling.
//
// A stopped turn drops the partial answer rather than resyncing: unlike an
// interview turn, nothing is persisted server-side until the stream
// completes (see qa/__init__.py's `_framed_answer`), so there is nothing to recover
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
  // Each turn shows only its own thinking and its own reply in progress,
  // so drop the previous turn's -- mirrors submitComposerMessage.
  deps.setAgentReasoning('');
  deps.setAgentDraft('');
  const {sinks, result} = buildAskSinks(deps);
  const signal = beginTurnAbort(deps);
  try {
    await askRunQuestion(runId, text, sinks, signal);
    const {answer, reasoning, sources} = result();
    appendChatMessage(deps.setMessages, {
      role: 'assistant',
      content: answer,
      reasoning: reasoning || undefined,
      sources,
    });
  } catch (error) {
    if (!isAbortError(error)) deps.setError(describeAskError(error));
  } finally {
    deps.turnAbortRef.current = null;
    deps.setIsStarting(false);
    settleTurn(deps);
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

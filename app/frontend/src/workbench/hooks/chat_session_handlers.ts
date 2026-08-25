import {type FormEvent} from 'react';
import {
  addInterviewTurn,
  createInterview,
  stageDocument,
  type Interview,
  type InterviewSinks,
  type StagedDocument,
} from '@/api/runs';
import {type InferredRunSpec} from '../run_spec';
import {copyText} from '@/lib/clipboard';
import {announceChatsChanged} from './chat_history_context';
import {appendChatMessage, emitDiagnosticEvent} from './chat_session_helpers';
import {
  applyAgentTurn,
  beginTurnAbort,
  describeSubmitError,
  isAbortError,
  recoverFromStoppedTurn,
} from './chat_session_handlers_shared';
import {
  editUserMessage,
  retryAssistantMessage,
  retryDraftSpec,
} from './chat_session_handlers_revise';
import {submitRunQuestion} from './chat_session_handlers_qa';
import {promoteDraftToRun} from './chat_session_start_run';
import {type ChatEntry} from '../pages/chat_timeline_cards';
import {type ChatSessionDeps, type HandlerDeps} from './chat_session_types';
import {type ComposerLog, type RunSpecLifecycle} from './chat_session_state';

// The handler-bag slice a composer submit reads, plus the two values only the
// submit event itself supplies. Projected off HandlerDeps rather than
// restated, so a field that changes shape there cannot drift out of sync here.
type SubmitComposerDeps = Pick<
  HandlerDeps,
  | 'input'
  | 'interview'
  | 'startedSession'
  | 'audience'
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
  e: FormEvent<HTMLFormElement>;
  files: File[];
};

// Clears the composer for a new turn; returns the trimmed text, or null
// when there is nothing to submit.
function beginComposerTurn(deps: SubmitComposerDeps): string | null {
  const text = deps.input.trim();
  if (!text) return null;
  deps.setInput('');
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
// already in progress, else starts a fresh one for the current audience.
function startInterviewTurn(
  deps: Pick<SubmitComposerDeps, 'interview' | 'audience'>,
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
  return createInterview(
    text,
    sinks,
    deps.audience ?? undefined,
    documentIds,
    signal,
  );
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
  deps.e.preventDefault();
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
    deps.setIsAwaitingAgent(false);
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

// Re-stages an already confirmed/started spec as an editable draft (the
// "edit plan" affordance on a spec card). Takes its dependencies as arguments
// instead of closing over hook state.
function editPlan({
  spec,
  stageDraftSpec,
  focusComposer,
}: Pick<HandlerDeps, 'stageDraftSpec' | 'focusComposer'> & {
  spec: InferredRunSpec;
}) {
  stageDraftSpec(spec);
  focusComposer();
  emitDiagnosticEvent({
    stage: 'CHAT',
    payload: {event: 'plan_edit_requested'},
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
 * chat_session_handlers_revise.ts) or closes directly over the one or two
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
    handleEditPlan: (spec: InferredRunSpec) => editPlan({spec, ...handlerDeps}),
    // A started run's interview is closed server-side, so submit routes to
    // the run's own Q&A endpoint instead of ever posting another interview
    // turn (A17). Read at call time (handlerDeps is the live view over the
    // latest render's state -- see liveHandlerDeps), so this cannot drift
    // behind a stale render.
    handleSubmit: (e: FormEvent<HTMLFormElement>, files: File[] = []) =>
      handlerDeps.startedSession
        ? submitRunQuestion({e, ...handlerDeps})
        : submitComposerMessage({e, files, ...handlerDeps}),
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
    paperCorpusEnabled: view.paperCorpusEnabled,
    audience: view.audience,
  };
}

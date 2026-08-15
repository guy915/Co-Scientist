import {type FormEvent} from 'react';
import {
  addInterviewTurn,
  createInterview,
  editInterviewTurn,
  retryInterviewTurn,
  stageDocument,
  type Interview,
  type InterviewSinks,
  type StagedDocument,
} from '@/api/runs';
import {type InferredRunSpec} from '../run_spec';
import {copyText} from '@/lib/clipboard';
import {type ChatEntry} from '../pages/chat_timeline_cards';
import {announceChatsChanged} from './chat_history_context';
import {appendChatMessage, emitDiagnosticEvent} from './chat_session_helpers';
import {promoteDraftToRun} from './chat_session_start_run';
import {applyInterview, type TranscriptSink} from './chat_session_transcript';
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
  | 'setPendingAttachments'
  | 'setDraft'
  | 'setConfirmed'
  | 'stageDraftSpec'
> & {
  e: FormEvent<HTMLFormElement>;
  files: File[];
};

// Applies the Agent's reply for one interview turn to the chat log.
//
// The server's interview is the whole conversation, not a delta, so the log
// is rebuilt from it rather than appended to. That is what gives every bubble
// the durable turn id an edit or a retry addresses, and it means a turn that
// removed earlier turns (a revision) needs no special handling here: they are
// simply absent from the snapshot that came back.
function applyAgentTurn(updated: Interview, deps: TranscriptSink): void {
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
): Promise<Interview> {
  if (deps.interview) {
    return addInterviewTurn(deps.interview.id, text, sinks, documentIds);
  }
  return createInterview(text, sinks, deps.audience ?? undefined, documentIds);
}

// User-facing message for a failed interview turn.
function describeSubmitError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The Agent could not continue the interview.';
}

// Composer submit advances the durable Agent interview. The browser never
// derives scientific setup fields from keywords; only the persisted model
// response can complete the setup and produce a runnable specification.
async function submitComposerMessage(deps: SubmitComposerDeps): Promise<void> {
  deps.e.preventDefault();
  // A started run consumed the interview: the server completed it when the
  // run was created, so it rejects further turns. The composer is disabled
  // in the UI from the moment the start round trip succeeds; this guard
  // keys off that same started-session state so no path posts another turn
  // until the session resets to a new chat.
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
  try {
    const staged = await stageTurnFiles(deps);
    const updated = await startInterviewTurn(
      deps,
      text,
      sinks,
      staged.map(document => document.id),
    );
    deps.setInterview(updated);
    // The chat exists server-side from here on: list it in the rail, and on
    // its first turn put its id in the URL so reloading or reopening it
    // returns to this conversation rather than a blank workspace.
    announceChatsChanged();
    if (isFirstTurn) deps.onChatStarted(updated.id);
    applyAgentTurn(updated, deps);
  } catch (error) {
    deps.setError(describeSubmitError(error));
  } finally {
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
  revise: (sinks: InterviewSinks) => Promise<Interview>,
): Promise<void> {
  deps.setError(null);
  deps.setToast(null);
  deps.setIsAwaitingAgent(true);
  deps.setAgentReasoning('');
  deps.setAgentDraft('');
  try {
    const updated = await revise({
      onReasoning: fragment =>
        deps.setAgentReasoning(current => current + fragment),
      onProse: fragment => deps.setAgentDraft(current => current + fragment),
    });
    applyAgentTurn(updated, deps);
    announceChatsChanged();
  } catch (error) {
    deps.setError(describeSubmitError(error));
  } finally {
    deps.setIsAwaitingAgent(false);
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

// Rewrites a scientist prompt where it stands and re-answers from there.
function editUserMessage(
  deps: HandlerDeps,
  message: ChatEntry,
  content: string,
): void {
  const target = revisableTurn(deps, message);
  const text = content.trim();
  if (!target || !text) return;
  deps.setMessages(current => truncateAtMessage(current, message, text));
  void reviseInterviewTurn(deps, sinks =>
    editInterviewTurn(target.interviewId, target.turnId, text, sinks),
  );
  emitDiagnosticEvent({stage: 'CHAT', payload: {event: 'prompt_edited'}});
}

// Discards an Agent answer and asks for another in its place.
function retryAssistantMessage(deps: HandlerDeps, message: ChatEntry): void {
  const target = revisableTurn(deps, message);
  if (!target) return;
  deps.setMessages(current => truncateAtMessage(current, message));
  void reviseInterviewTurn(deps, sinks =>
    retryInterviewTurn(target.interviewId, target.turnId, sinks),
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
function retryDraftSpec(deps: HandlerDeps): void {
  // Locked once a run has started; see revisableTurn. Rehydration can leave
  // a draft staged alongside a started session, so the check is not redundant
  // with the draft being null.
  if (deps.startedSession) return;
  const target = draftRevisionTarget(deps);
  if (!target) return;
  deps.setDraft(null);
  void reviseInterviewTurn(deps, sinks =>
    retryInterviewTurn(target.interviewId, target.turnId, sinks),
  );
  emitDiagnosticEvent({stage: 'CHAT', payload: {event: 'plan_retried'}});
}

/**
 * Builds the full wrapped-handler set from a `handlerDeps` bag: each handler
 * below either forwards to one of the module-level functions above or closes
 * directly over the one or two deps it needs. Takes no hooks itself (plain
 * function, not a sub-hook), so it can be called unconditionally from anywhere
 * in useChatSession's body.
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
    handleSubmit: (e: FormEvent<HTMLFormElement>, files: File[] = []) =>
      submitComposerMessage({e, files, ...handlerDeps}),
    handleStartRun: () => promoteDraftToRun(handlerDeps),
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

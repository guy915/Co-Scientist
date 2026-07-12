import {type Dispatch, type FormEvent, type SetStateAction} from 'react';
import {inferRunSpec, type InferredRunSpec, reviseRunSpec} from '../run_spec';
import {copyText} from '@/lib/clipboard';
import {conciseTitle} from '@/lib/text';
import {type ChatEntry} from '../pages/chat_timeline_cards';
import {type ToastState} from './use_toast';
import {appendChatMessage, emitDiagnosticEvent} from './chat_session_helpers';
import {promoteDraftToRun} from './chat_session_start_run';
import {
  type ChatSessionDeps,
  type HandlerDeps,
  type SpecStage,
} from './chat_session_types';
import {type ComposerLog, type RunSpecLifecycle} from './chat_session_state';

// Revises the staged draft against a follow-up message and acknowledges it
// in the chat log. Split out of submitComposerMessage so that function's two
// branches (revise vs. infer) each read as a single call.
function reviseDraftFromMessage({
  draftSpec,
  text,
  sentAt,
  setMessages,
  stageDraftSpec,
}: {
  draftSpec: InferredRunSpec;
  text: string;
  sentAt: number;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
}): void {
  const next = reviseRunSpec(draftSpec, text);
  // The +0.001/+0.002 offsets keep the spec card and the assistant reply
  // ordered strictly after the user message in the timeline sort.
  stageDraftSpec(next, sentAt + 0.001);
  appendChatMessage(
    setMessages,
    'assistant',
    'I updated the run setup. Start it when the spec looks right.',
    sentAt + 0.002,
  );
  emitDiagnosticEvent({
    stage: 'CHAT',
    run: conciseTitle(next.goal),
    payload: {event: 'draft_revised'},
  });
}

// Infers a brand-new draft spec from the message's text. Split out of
// submitComposerMessage alongside reviseDraftFromMessage.
function createDraftFromMessage({
  text,
  sentAt,
  stageDraftSpec,
}: {
  text: string;
  sentAt: number;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
}): void {
  const next = inferRunSpec(text);
  stageDraftSpec(next, sentAt + 0.001);
  emitDiagnosticEvent({
    stage: 'LIFECYCLE',
    run: conciseTitle(next.goal),
    payload: {event: 'draft_created'},
  });
}

// Composer submit. With a draft staged, the message is treated as a revision
// instruction against it; otherwise it becomes the research goal a brand-new
// draft spec is inferred from. Nothing hits the API here -- runs are only
// created/started in handleStartRun. Takes its dependencies as arguments
// instead of closing over hook state.
async function submitComposerMessage({
  e,
  input,
  draft,
  setInput,
  setError,
  setToast,
  setMessages,
  stageDraftSpec,
}: {
  e: FormEvent<HTMLFormElement>;
  input: string;
  draft: SpecStage | null;
  setInput: (value: string) => void;
  setError: (message: string | null) => void;
  setToast: (value: string | ToastState | null) => void;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
}): Promise<void> {
  e.preventDefault();
  const text = input.trim();
  if (!text) return;
  setInput('');
  setError(null);
  setToast(null);

  const sentAt = appendChatMessage(setMessages, 'user', text);
  if (draft) {
    reviseDraftFromMessage({
      draftSpec: draft.spec,
      text,
      sentAt,
      setMessages,
      stageDraftSpec,
    });
  } else {
    createDraftFromMessage({text, sentAt, stageDraftSpec});
  }
}

// Cancels the draft and clears the whole conversation (not just the spec),
// returning the workspace to its empty state. Takes its dependencies as
// arguments instead of closing over hook state.
function cancelDraftSpec({
  draft,
  setInput,
  clearSessionState,
  setMessages,
  setError,
  setToast,
}: {
  draft: SpecStage | null;
  setInput: (value: string) => void;
  clearSessionState: () => void;
  setMessages: (value: ChatEntry[]) => void;
  setError: (message: string | null) => void;
  setToast: (value: string | ToastState | null) => void;
}) {
  const title = draft ? conciseTitle(draft.spec.goal) : undefined;
  setInput('');
  clearSessionState();
  setMessages([]);
  setError(null);
  setToast('The session was canceled');
  emitDiagnosticEvent({
    stage: 'LIFECYCLE',
    run: title,
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
}: {
  spec: InferredRunSpec;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
  focusComposer: () => void;
}) {
  stageDraftSpec(spec);
  focusComposer();
  emitDiagnosticEvent({
    stage: 'CHAT',
    run: conciseTitle(spec.goal),
    payload: {event: 'plan_edit_requested'},
  });
}

// Copies a message's prompt text and offers a "Start new chat" toast action
// that clears the session and prefills the composer with it. Takes its
// dependencies as arguments instead of closing over hook state.
async function copyMessagePrompt({
  message,
  clearSessionState,
  setMessages,
  setError,
  setToast,
  setInput,
  focusComposer,
}: {
  message: ChatEntry;
  clearSessionState: () => void;
  setMessages: (value: ChatEntry[]) => void;
  setError: (message: string | null) => void;
  setToast: (value: string | ToastState | null) => void;
  setInput: (value: string) => void;
  focusComposer: () => void;
}): Promise<void> {
  await copyText(message.content);
  const promptText = message.content;
  // Copy is a pure utility (matching the reference): it does not stage a
  // draft. The toast offers "Start new chat", which clears the session and
  // prefills the composer with the copied prompt.
  setToast({
    message: 'Prompt copied',
    action: {
      label: 'Start new chat',
      onClick: () => {
        clearSessionState();
        setMessages([]);
        setError(null);
        setToast(null);
        setInput(promptText);
        focusComposer();
      },
    },
  });
  emitDiagnosticEvent({
    stage: 'CHAT',
    run: conciseTitle(promptText),
    payload: {event: 'prompt_copied'},
  });
}

// Re-emits the assistant message as a fresh bubble at the end of the log.
function retryAssistantMessage(
  message: ChatEntry,
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>,
): void {
  appendChatMessage(setMessages, 'assistant', message.content);
}

// Loads a previous message back into the composer for editing.
function loadMessageIntoComposer(
  message: ChatEntry,
  setInput: (value: string) => void,
  focusComposer: () => void,
): void {
  setInput(message.content);
  focusComposer();
}

// Re-runs spec inference from the draft's goal, discarding any revisions.
function retryDraftSpec(
  draft: SpecStage | null,
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void,
): void {
  if (!draft) return;
  stageDraftSpec(inferRunSpec(draft.spec.goal));
}

/**
 * Builds the full wrapped-handler set from a `handlerDeps` bag: each handler
 * below either forwards to one of the module-level functions above or closes
 * directly over the one or two deps it needs. Takes no hooks itself (plain
 * function, not a sub-hook), so it can be called unconditionally from anywhere
 * in useChatSession's body.
 */
export function buildChatHandlers(handlerDeps: HandlerDeps) {
  const {setInput, setMessages, focusComposer, draft, stageDraftSpec} =
    handlerDeps;

  return {
    handleRetryMessage: (message: ChatEntry) =>
      retryAssistantMessage(message, setMessages),
    handleEditMessage: (message: ChatEntry) =>
      loadMessageIntoComposer(message, setInput, focusComposer),
    handleCopyRequest: (message: ChatEntry) =>
      copyMessagePrompt({message, ...handlerDeps}),
    handleRetryDraftSpec: () => retryDraftSpec(draft, stageDraftSpec),
    handleCancelDraftSpec: () => cancelDraftSpec(handlerDeps),
    handleEditPlan: (spec: InferredRunSpec) => editPlan({spec, ...handlerDeps}),
    handleSubmit: (e: FormEvent<HTMLFormElement>) =>
      submitComposerMessage({e, ...handlerDeps}),
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
    setDraft: lifecycle.setDraft,
    setConfirmed: lifecycle.setConfirmed,
    setStartedSession: lifecycle.setStartedSession,
    setIsStarting: composer.setIsStarting,
    setMessages: composer.setMessages,
    setError: composer.setError,
    setToast: view.setToast,
    clearSessionState: lifecycle.clearSessionState,
    stageDraftSpec: lifecycle.stageDraftSpec,
    focusComposer: view.focusComposer,
    reloadHistory: view.reloadHistory,
    pubmedEnabled: view.pubmedEnabled,
  };
}

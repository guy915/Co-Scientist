import {type Dispatch, type FormEvent, type SetStateAction} from 'react';
import {addInterviewTurn, createInterview, type Interview} from '@/api/runs';
import {interviewToRunSpec, type InferredRunSpec} from '../run_spec';
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

// Composer submit advances the durable Agent interview. The browser never
// derives scientific setup fields from keywords; only the persisted model
// response can complete the setup and produce a runnable specification.
async function submitComposerMessage({
  e,
  files,
  input,
  interview,
  setInput,
  setError,
  setToast,
  setMessages,
  setInterview,
  setIsStarting,
  setIsAwaitingAgent,
  setAgentReasoning,
  setPendingAttachments,
  stageDraftSpec,
}: {
  e: FormEvent<HTMLFormElement>;
  files: File[];
  input: string;
  interview: Interview | null;
  setInput: (value: string) => void;
  setError: (message: string | null) => void;
  setToast: (value: string | ToastState | null) => void;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  setInterview: (interview: Interview | null) => void;
  setIsStarting: (value: boolean) => void;
  setIsAwaitingAgent: (value: boolean) => void;
  setAgentReasoning: Dispatch<SetStateAction<string>>;
  setPendingAttachments: Dispatch<SetStateAction<File[]>>;
  stageDraftSpec: (
    spec: InferredRunSpec,
    createdAt?: number,
    intro?: string,
  ) => void;
}): Promise<void> {
  e.preventDefault();
  const text = input.trim();
  if (!text) return;
  if (files.length) {
    setPendingAttachments(current => [...current, ...files]);
  }
  setInput('');
  setError(null);
  setToast(null);

  const sentAt = appendChatMessage(setMessages, 'user', text);
  setIsStarting(true);
  setIsAwaitingAgent(true);
  // Each turn shows only its own thinking, so drop the previous turn's.
  setAgentReasoning('');
  const onReasoning = (fragment: string) =>
    setAgentReasoning(current => current + fragment);
  try {
    const updated = interview
      ? await addInterviewTurn(interview.id, text, onReasoning)
      : await createInterview(text, onReasoning);
    setInterview(updated);
    const agentTurn = [...updated.turns]
      .reverse()
      .find(turn => turn.role === 'agent');
    if (updated.status === 'completed') {
      // The interview is done: fold the Agent's closing message into the plan
      // card as its intro, so the completed turn reads as one response (the
      // plan) rather than an assistant bubble followed by a separate card.
      const spec = interviewToRunSpec(updated);
      stageDraftSpec(spec, sentAt + 0.002, agentTurn?.content);
      emitDiagnosticEvent({
        stage: 'LIFECYCLE',
        run: conciseTitle(spec.goal),
        payload: {event: 'interview_completed', interview_id: updated.id},
      });
    } else {
      // Still interviewing: the Agent's reply is a follow-up question, shown
      // as its own assistant bubble.
      if (agentTurn) {
        appendChatMessage(
          setMessages,
          'assistant',
          agentTurn.content,
          sentAt + 0.001,
        );
      }
      emitDiagnosticEvent({
        stage: 'CHAT',
        run: conciseTitle(updated.fields.research_challenge),
        payload: {event: 'interview_advanced', interview_id: updated.id},
      });
    }
  } catch (error) {
    setError(
      error instanceof Error
        ? error.message
        : 'The Agent could not continue the interview.',
    );
  } finally {
    setIsStarting(false);
    setIsAwaitingAgent(false);
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

// Re-stages the persisted Agent derivation without recomputing it locally.
function retryDraftSpec(
  draft: SpecStage | null,
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void,
): void {
  if (!draft) return;
  stageDraftSpec(draft.spec);
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
    setInterview: lifecycle.setInterview,
    setDraft: lifecycle.setDraft,
    setConfirmed: lifecycle.setConfirmed,
    setStartedSession: lifecycle.setStartedSession,
    setIsStarting: composer.setIsStarting,
    setIsAwaitingAgent: composer.setIsAwaitingAgent,
    setAgentReasoning: composer.setAgentReasoning,
    setMessages: composer.setMessages,
    setError: composer.setError,
    pendingAttachments: composer.pendingAttachments,
    setPendingAttachments: composer.setPendingAttachments,
    setToast: view.setToast,
    clearSessionState: lifecycle.clearSessionState,
    stageDraftSpec: lifecycle.stageDraftSpec,
    focusComposer: view.focusComposer,
    reloadHistory: view.reloadHistory,
    pubmedEnabled: view.pubmedEnabled,
  };
}

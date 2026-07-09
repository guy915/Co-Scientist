import {
  type Dispatch,
  type FormEvent,
  type SetStateAction,
  useCallback,
  useState,
} from 'react';
import {createRun, startRun} from '@/api/runs';
import {inferRunSpec, type InferredRunSpec, reviseRunSpec} from '../run_spec';
import {copyText} from '@/lib/clipboard';
import {makePrefixedId} from '@/lib/id';
import {
  type ChatEntry,
  referenceSetupTitle,
  type StartedSession,
} from '../pages/chat_timeline_cards';
import {type ToastState} from './use_toast';

// Fire-and-forget diagnostic line for the shell's Logs popover
// (DiagnosticsControl in layout_diagnostics.tsx listens for this event); a
// window event keeps this hook decoupled from the shell component.
function emitDiagnosticEvent({
  stage,
  run,
  level = 'info',
  payload = {},
}: {
  stage: string;
  run?: string;
  level?: 'info' | 'success' | 'error';
  payload?: Record<string, unknown>;
}) {
  window.dispatchEvent(
    new CustomEvent('cosci-diagnostic-event', {
      detail: {stage, run, level, payload},
    }),
  );
}

/** View-layer collaborators the session needs but does not own. */
interface ChatSessionDeps {
  reloadHistory: () => Promise<void>;
  focusComposer: () => void;
  setToast: (value: string | ToastState | null) => void;
  pubmedEnabled: boolean;
}

// Appends a chat bubble; timestamps are epoch seconds (matching the API's
// created_at convention) and returned so callers can order follow-up entries
// relative to this one. Takes `setMessages` as an argument instead of
// closing over hook state so every handler that appends a message can share
// it without each needing its own copy.
function appendChatMessage(
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>,
  role: 'assistant' | 'user',
  content: string,
  createdAt = Date.now() / 1000,
): number {
  setMessages(prev => [
    ...prev,
    {
      id: makePrefixedId(role),
      role,
      content,
      created_at: createdAt,
    },
  ]);
  return createdAt;
}

/**
 * Sub-hook owning the spec lifecycle state machine: draftSpec (inferred from
 * the first submit, revisable by follow-up messages) -> confirmedSpec
 * (frozen at start) -> startedSession (the created+started run), plus the
 * transition helpers that only touch this state. Called unconditionally from
 * the top of useChatSession, so its hook call order stays fixed across
 * renders.
 */
function useRunSpecLifecycle() {
  const [draftSpec, setDraftSpec] = useState<InferredRunSpec | null>(null);
  const [draftSpecCreatedAt, setDraftSpecCreatedAt] = useState<number | null>(
    null,
  );
  const [confirmedSpec, setConfirmedSpec] = useState<InferredRunSpec | null>(
    null,
  );
  const [confirmedSpecCreatedAt, setConfirmedSpecCreatedAt] = useState<
    number | null
  >(null);
  const [startedSession, setStartedSession] = useState<StartedSession | null>(
    null,
  );

  // Drops all spec/session stages but keeps the message log; useCallback so
  // resetSession (which depends on it) also stays referentially stable.
  const clearSessionState = useCallback(() => {
    setDraftSpec(null);
    setDraftSpecCreatedAt(null);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
  }, []);

  // Installs `spec` as the active draft and rolls back any later stages
  // (confirmed/started), since a new draft restarts the lifecycle.
  function stageDraftSpec(
    spec: InferredRunSpec,
    createdAt = Date.now() / 1000,
  ) {
    setDraftSpec(spec);
    setDraftSpecCreatedAt(createdAt);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
  }

  return {
    draftSpec,
    setDraftSpec,
    draftSpecCreatedAt,
    setDraftSpecCreatedAt,
    confirmedSpec,
    setConfirmedSpec,
    confirmedSpecCreatedAt,
    setConfirmedSpecCreatedAt,
    startedSession,
    setStartedSession,
    clearSessionState,
    stageDraftSpec,
  };
}

/**
 * Sub-hook owning the composer's own state: the input text, the in-flight
 * flag, the chat log, and the last error, plus the full-session reset. Takes
 * `clearSessionState` (from {@link useRunSpecLifecycle}) as an argument since
 * resetSession has to wipe both slices together.
 */
function useComposerLog(clearSessionState: () => void) {
  // Composer text; this stage feeds draftSpec on submit.
  const [input, setInput] = useState('');
  // True while the create+start round trip is in flight; the view uses it to
  // disable the Start control against double submission.
  const [isStarting, setIsStarting] = useState(false);
  // Append-only log of user/assistant chat bubbles (spec cards are rendered
  // from the spec state, not stored here).
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Full wipe back to the pristine composer, used by "New chat"; stable
  // identity so callers can hang effects off it.
  const resetSession = useCallback(() => {
    clearSessionState();
    setInput('');
    setIsStarting(false);
    setMessages([]);
    setError(null);
  }, [clearSessionState]);

  return {
    input,
    setInput,
    isStarting,
    setIsStarting,
    messages,
    setMessages,
    error,
    setError,
    resetSession,
  };
}

/**
 * Runs the create+start API round trip for a confirmed draft spec and
 * applies the resulting state transitions and diagnostic events. Pulled out
 * of the hook so it takes every value and setter it needs as an argument
 * instead of closing over hook state (it calls no hooks itself).
 */
async function startDraftRun({
  specToStart,
  specCreatedAt,
  pubmedEnabled,
  reloadHistory,
  setConfirmedSpec,
  setConfirmedSpecCreatedAt,
  setDraftSpec,
  setDraftSpecCreatedAt,
  setStartedSession,
  setError,
}: {
  specToStart: InferredRunSpec;
  specCreatedAt: number;
  pubmedEnabled: boolean;
  reloadHistory: () => Promise<void>;
  setConfirmedSpec: (spec: InferredRunSpec) => void;
  setConfirmedSpecCreatedAt: (createdAt: number) => void;
  setDraftSpec: (spec: InferredRunSpec | null) => void;
  setDraftSpecCreatedAt: (createdAt: number | null) => void;
  setStartedSession: (session: StartedSession) => void;
  setError: (message: string) => void;
}): Promise<void> {
  emitDiagnosticEvent({
    stage: 'LIFECYCLE',
    run: referenceSetupTitle(specToStart.goal),
    payload: {event: 'start_requested'},
  });
  try {
    const created = await createRun({
      research_goal: specToStart.goal,
      requirements: specToStart.requirements,
      attributes: specToStart.attributes,
      criteria: specToStart.criteria,
      focus: specToStart.focus,
      tier: specToStart.tier,
      enable_literature_review: pubmedEnabled,
    });
    const session: StartedSession = {
      id: created.id,
      title: referenceSetupTitle(specToStart.goal),
      at: Date.now() / 1000,
    };
    setConfirmedSpec(specToStart);
    setConfirmedSpecCreatedAt(specCreatedAt);
    setDraftSpec(null);
    setDraftSpecCreatedAt(null);
    await startRun(created.id);
    setStartedSession(session);
    await reloadHistory();
    // Tell the shell sidebar (which owns a separate history copy) that a new
    // run exists, so it appears immediately instead of only after a reload.
    window.dispatchEvent(new Event('cosci-runs-changed'));
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: session.title,
      level: 'success',
      payload: {event: 'start_queued', run_id: created.id},
    });
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: referenceSetupTitle(specToStart.goal),
      level: 'error',
      payload: {
        event: 'start_failed',
        message: err instanceof Error ? err.message : String(err),
      },
    });
  }
}

// Promotes the draft to a real run: createRun (POST /api/runs) then startRun
// (POST /api/runs/{id}/start). The draft becomes the confirmed spec once
// creation succeeds; if createRun itself fails the draft stays staged so the
// user can retry, and either failure surfaces via `error`. Pulled out of the
// hook so it takes its dependencies as a single argument instead of closing
// over hook state.
async function promoteDraftToRun({
  draftSpec,
  draftSpecCreatedAt,
  pubmedEnabled,
  reloadHistory,
  setIsStarting,
  setError,
  setToast,
  setConfirmedSpec,
  setConfirmedSpecCreatedAt,
  setDraftSpec,
  setDraftSpecCreatedAt,
  setStartedSession,
}: {
  draftSpec: InferredRunSpec | null;
  draftSpecCreatedAt: number | null;
  pubmedEnabled: boolean;
  reloadHistory: () => Promise<void>;
  setIsStarting: (value: boolean) => void;
  setError: (message: string | null) => void;
  setToast: (value: string | ToastState | null) => void;
  setConfirmedSpec: (spec: InferredRunSpec) => void;
  setConfirmedSpecCreatedAt: (createdAt: number) => void;
  setDraftSpec: (spec: InferredRunSpec | null) => void;
  setDraftSpecCreatedAt: (createdAt: number | null) => void;
  setStartedSession: (session: StartedSession) => void;
}): Promise<void> {
  if (!draftSpec) return;
  // Snapshot the draft up front so state changes during the awaits below
  // can't swap the spec out from under this start attempt.
  const specToStart = draftSpec;
  const specCreatedAt = draftSpecCreatedAt ?? Date.now() / 1000;
  setIsStarting(true);
  setError(null);
  setToast(null);
  try {
    await startDraftRun({
      specToStart,
      specCreatedAt,
      pubmedEnabled,
      reloadHistory,
      setConfirmedSpec,
      setConfirmedSpecCreatedAt,
      setDraftSpec,
      setDraftSpecCreatedAt,
      setStartedSession,
      setError,
    });
  } finally {
    setIsStarting(false);
  }
}

// Composer submit. With a draft staged, the message is treated as a revision
// instruction against it; otherwise it becomes the research goal a brand-new
// draft spec is inferred from. Nothing hits the API here -- runs are only
// created/started in handleStartRun. Pulled out of the hook so it takes its
// dependencies as arguments instead of closing over hook state.
async function submitComposerMessage({
  e,
  input,
  draftSpec,
  setInput,
  setError,
  setToast,
  setMessages,
  stageDraftSpec,
}: {
  e: FormEvent<HTMLFormElement>;
  input: string;
  draftSpec: InferredRunSpec | null;
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

  if (draftSpec) {
    const sentAt = appendChatMessage(setMessages, 'user', text);
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
      run: referenceSetupTitle(next.goal),
      payload: {event: 'draft_revised'},
    });
    return;
  }

  const sentAt = appendChatMessage(setMessages, 'user', text);
  const next = inferRunSpec(text);
  stageDraftSpec(next, sentAt + 0.001);
  emitDiagnosticEvent({
    stage: 'LIFECYCLE',
    run: referenceSetupTitle(next.goal),
    payload: {event: 'draft_created'},
  });
}

// Cancels the draft and clears the whole conversation (not just the spec),
// returning the workspace to its empty state. Pulled out of the hook so it
// takes its dependencies as arguments instead of closing over hook state.
function cancelDraftSpec({
  draftSpec,
  setInput,
  clearSessionState,
  setMessages,
  setError,
  setToast,
}: {
  draftSpec: InferredRunSpec | null;
  setInput: (value: string) => void;
  clearSessionState: () => void;
  setMessages: (value: ChatEntry[]) => void;
  setError: (message: string | null) => void;
  setToast: (value: string | ToastState | null) => void;
}) {
  const title = draftSpec ? referenceSetupTitle(draftSpec.goal) : undefined;
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
// "edit plan" affordance on a spec card). Pulled out of the hook so it takes
// its dependencies as arguments instead of closing over hook state.
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
    run: referenceSetupTitle(spec.goal),
    payload: {event: 'plan_edit_requested'},
  });
}

// Copies a message's prompt text and offers a "Start new chat" toast action
// that clears the session and prefills the composer with it. Pulled out of
// the hook so it takes its dependencies as arguments instead of closing over
// hook state.
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
    run: referenceSetupTitle(promptText),
    payload: {event: 'prompt_copied'},
  });
}

/** Every value/setter the module-level handler functions above might need;
 * each handler passes this (optionally merged with a per-call value like
 * `message`) so it only has to name what it actually uses. */
interface HandlerDeps {
  input: string;
  setInput: (value: string) => void;
  draftSpec: InferredRunSpec | null;
  draftSpecCreatedAt: number | null;
  setDraftSpec: (spec: InferredRunSpec | null) => void;
  setDraftSpecCreatedAt: (createdAt: number | null) => void;
  setConfirmedSpec: (spec: InferredRunSpec) => void;
  setConfirmedSpecCreatedAt: (createdAt: number) => void;
  setStartedSession: (session: StartedSession) => void;
  setIsStarting: (value: boolean) => void;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  setError: (message: string | null) => void;
  setToast: (value: string | ToastState | null) => void;
  clearSessionState: () => void;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
  focusComposer: () => void;
  reloadHistory: () => Promise<void>;
  pubmedEnabled: boolean;
}

// Builds the full wrapped-handler set from a `handlerDeps` bag: each handler
// below either closes directly over the deps it needs or forwards the whole
// bag to one of the module-level functions above. Takes no hooks itself
// (plain function, not a sub-hook), so it can be called unconditionally from
// anywhere in useChatSession's body.
function buildChatHandlers(handlerDeps: HandlerDeps) {
  const {setInput, setMessages, focusComposer, draftSpec, stageDraftSpec} =
    handlerDeps;

  // Re-emits the assistant message as a fresh bubble at the end of the log.
  function handleRetryMessage(message: ChatEntry) {
    appendChatMessage(setMessages, 'assistant', message.content);
  }

  // Loads a previous message back into the composer for editing.
  function handleEditMessage(message: ChatEntry) {
    setInput(message.content);
    focusComposer();
  }

  const handleCopyRequest = (message: ChatEntry) =>
    copyMessagePrompt({message, ...handlerDeps});

  // Re-runs spec inference from the draft's goal, discarding any revisions.
  function handleRetryDraftSpec() {
    if (!draftSpec) return;
    stageDraftSpec(inferRunSpec(draftSpec.goal));
  }

  const handleCancelDraftSpec = () => cancelDraftSpec(handlerDeps);

  const handleEditPlan = (spec: InferredRunSpec) =>
    editPlan({spec, ...handlerDeps});

  const handleSubmit = (e: FormEvent<HTMLFormElement>) =>
    submitComposerMessage({e, ...handlerDeps});

  const handleStartRun = () => promoteDraftToRun(handlerDeps);

  return {
    handleRetryMessage,
    handleEditMessage,
    handleCopyRequest,
    handleRetryDraftSpec,
    handleCancelDraftSpec,
    handleEditPlan,
    handleSubmit,
    handleStartRun,
  };
}

/**
 * Owns the chat workspace's session state machine: the composer input, the
 * message log, the draft/confirmed run specs, and the started session, plus
 * every handler that transitions between them. State is delegated to the
 * {@link useRunSpecLifecycle} and {@link useComposerLog} sub-hooks; the
 * heavier handlers are the module-level functions above, wrapped by
 * {@link buildChatHandlers} against a shared `handlerDeps` bag. View concerns
 * (history reload, composer focus, toasts) are injected via
 * {@link ChatSessionDeps}.
 */
export function useChatSession({
  reloadHistory,
  focusComposer,
  setToast,
  pubmedEnabled,
}: ChatSessionDeps) {
  const {
    draftSpec,
    setDraftSpec,
    draftSpecCreatedAt,
    setDraftSpecCreatedAt,
    confirmedSpec,
    setConfirmedSpec,
    confirmedSpecCreatedAt,
    setConfirmedSpecCreatedAt,
    startedSession,
    setStartedSession,
    clearSessionState,
    stageDraftSpec,
  } = useRunSpecLifecycle();
  const {
    input,
    setInput,
    isStarting,
    setIsStarting,
    messages,
    setMessages,
    error,
    setError,
    resetSession,
  } = useComposerLog(clearSessionState);

  // Anything at all in the session? Drives the empty-state vs timeline view.
  const hasConversation =
    messages.length > 0 ||
    Boolean(draftSpec) ||
    Boolean(confirmedSpec) ||
    Boolean(startedSession);

  // Every value/setter the module-level handler functions above might need;
  // see {@link buildChatHandlers} for how each handler consumes this.
  const handlerDeps: HandlerDeps = {
    input,
    setInput,
    draftSpec,
    draftSpecCreatedAt,
    setDraftSpec,
    setDraftSpecCreatedAt,
    setConfirmedSpec,
    setConfirmedSpecCreatedAt,
    setStartedSession,
    setIsStarting,
    setMessages,
    setError,
    setToast,
    clearSessionState,
    stageDraftSpec,
    focusComposer,
    reloadHistory,
    pubmedEnabled,
  };
  const handlers = buildChatHandlers(handlerDeps);

  // Exposed surface: raw state + setters for the view to render the
  // timeline, and the handler set that encodes every legal transition.
  return {
    input,
    setInput,
    draftSpec,
    setDraftSpec,
    draftSpecCreatedAt,
    confirmedSpec,
    confirmedSpecCreatedAt,
    startedSession,
    setStartedSession,
    isStarting,
    messages,
    error,
    hasConversation,
    resetSession,
    stageDraftSpec,
    ...handlers,
  };
}

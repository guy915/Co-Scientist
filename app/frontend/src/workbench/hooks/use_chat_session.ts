import {liveHandlerDeps} from './chat_session_transcript';
import {
  useLayoutEffect,
  useMemo,
  useRef,
  type Dispatch,
  type RefObject,
  type SetStateAction,
  useCallback,
  useState,
} from 'react';
import {buildChatHandlers, toHandlerDeps} from './chat_session_handlers';
import type {InferredRunSpec} from '../run_spec';
import type {Interview, StagedDocument} from '@/api/runs';
import type {ChatEntry} from '../pages/chat_timeline_bubble';
import type {StartedSession} from '../pages/chat_timeline_run_spec_card';
import type {ToastSetter} from './use_toast';

/**
 * Owns the chat workspace's session state machine: the composer input, the
 * message log, the draft/confirmed run specs, and the started session, plus
 * every handler that transitions between them. State is delegated to the
 * {@link useRunSpecLifecycle} and {@link useComposerLog} sub-hooks; the
 * heavier handlers are the module-level functions in chat_session_handlers,
 * wrapped by {@link buildChatHandlers} against a shared `handlerDeps` bag
 * (assembled by {@link toHandlerDeps}). View concerns (history reload,
 * composer focus, toasts) are injected via {@link ChatSessionDeps}.
 */
export function useChatSession(deps: ChatSessionDeps) {
  const lifecycle = useRunSpecLifecycle();
  const composer = useComposerLog(lifecycle.clearSessionState);

  // Anything at all in the session? Drives the empty-state vs timeline view.
  const hasConversation =
    composer.messages.length > 0 ||
    Boolean(lifecycle.interview) ||
    Boolean(lifecycle.draft) ||
    Boolean(lifecycle.confirmed) ||
    Boolean(lifecycle.startedSession);

  // Handlers are built ONCE: the deps bag is re-assembled each render into a
  // ref (committed in a layout effect so aborted renders never leak into it),
  // and buildChatHandlers reads through a live getter view over that ref at
  // call time. Handler identities therefore stay stable across renders —
  // including the high-frequency ones from streamed agent reasoning — without
  // any handler seeing stale state.
  const handlerDepsBag = toHandlerDeps(lifecycle, composer, deps);
  const handlerDepsRef = useRef(handlerDepsBag);
  useLayoutEffect(() => {
    handlerDepsRef.current = handlerDepsBag;
  });
  const handlers = useMemo(
    () => buildChatHandlers(liveHandlerDeps(handlerDepsRef)),
    [],
  );

  // Exposed surface: raw state + setters for the view to render the
  // timeline, and the handler set that encodes every legal transition.
  return {
    input: composer.input,
    setInput: composer.setInput,
    draft: lifecycle.draft,
    interview: lifecycle.interview,
    setInterview: lifecycle.setInterview,
    setDraft: lifecycle.setDraft,
    confirmed: lifecycle.confirmed,
    setConfirmed: lifecycle.setConfirmed,
    startedSession: lifecycle.startedSession,
    setStartedSession: lifecycle.setStartedSession,
    isStarting: composer.isStarting,
    isAwaitingAgent: composer.isAwaitingAgent,
    agentReasoning: composer.agentReasoning,
    agentDraft: composer.agentDraft,
    messages: composer.messages,
    setMessages: composer.setMessages,
    error: composer.error,
    hasConversation,
    resetSession: composer.resetSession,
    stageDraftSpec: lifecycle.stageDraftSpec,
    ...handlers,
  };
}

/**
 * A staged run spec paired with the timeline timestamp it was created at.
 * Draft and confirmed specs each carry their own stamp, always set and
 * cleared together, so they live as one value rather than two parallel fields.
 */
export interface SpecStage {
  spec: InferredRunSpec;
  createdAt: number;
  // The Agent's closing interview message, shown as the plan card's lead-in so
  // a completed interview reads as one response instead of a bubble + a card.
  intro?: string;
  // The chain of thought behind that closing message, kept with it so the
  // completing turn keeps its thinking like every other turn does.
  reasoning?: string;
  // The durable interview turn that produced this plan. The card has no
  // bubble of its own, so this is what its retry addresses.
  turnId?: number;
  // True when the deterministic fallback authored that closing message (no
  // model reachable). The plan card shows the same quiet notice a fallback
  // bubble does, since the lead-in IS that turn.
  fallback?: boolean;
}

/** Run-resolution state used to render a safe, manual chat recovery action. */
export interface LinkedDraftRecovery {
  canContinueLinkedDraft: boolean;
  spec?: InferredRunSpec;
  status: 'checking' | 'error' | 'cancelled' | undefined;
  retryStatusLookup: () => void;
}

/** The Agent's closing turn, as staged onto the plan card. */
export interface DraftIntro {
  message?: string;
  reasoning?: string;
  turnId?: number;
  /** Whether the deterministic fallback authored the closing turn. */
  fallback?: boolean;
}

/** View-layer collaborators the session needs but does not own. */
export interface ChatSessionDeps {
  reloadHistory: () => Promise<void>;
  /**
   * Called with the durable chat id the moment a conversation becomes one,
   * so the page can put it in the URL. Until then a chat has no id to route
   * to -- the first turn is what creates it.
   */
  onChatStarted: (chatId: string) => void;
  focusComposer: () => void;
  setToast: ToastSetter;
  pubmedEnabled: boolean;
  webSearchEnabled: boolean;
}

/**
 * Dependencies shared by `executeStart` and `startDraftRun`: the snapshotted
 * draft stage plus the relevant slice of `HandlerDeps` (callers pass the
 * same values they received there).
 *
 * The whole stage, not just its spec: the confirmed stage is the same
 * completing turn frozen, so it has to carry that turn's closing message,
 * thinking and fallback marker across the start.
 */
export type ExecuteStartDeps = Pick<
  HandlerDeps,
  | 'pubmedEnabled'
  | 'webSearchEnabled'
  | 'reloadHistory'
  | 'setConfirmed'
  | 'setDraft'
  | 'setInput'
  | 'setStartedSession'
  | 'setIsAwaitingAgent'
  | 'setMessages'
  | 'pendingAttachments'
  | 'setPendingAttachments'
> & {
  stageToStart: SpecStage;
};

/**
 * Every value/setter the module-level handler functions might need; each
 * handler passes this (optionally merged with a per-call value like `message`)
 * so it only has to name what it actually uses.
 */
export interface HandlerDeps {
  input: string;
  setInput: (value: string) => void;
  draft: SpecStage | null;
  interview: Interview | null;
  // The run started by this session, once the create+start round trip has
  // succeeded. Its presence closes the interview server-side, so every path
  // that would post another turn reads it and refuses.
  startedSession: StartedSession | null;
  setInterview: (interview: Interview | null) => void;
  setDraft: (stage: SpecStage | null) => void;
  setConfirmed: (stage: SpecStage | null) => void;
  // A dispatch, not a plain setter: the Agent's start announcement streams
  // into the session already on screen (see chat_session_start_run.ts), so
  // its fragments have to merge into the current value rather than replace a
  // captured one.
  setStartedSession: Dispatch<SetStateAction<StartedSession | null>>;
  setIsStarting: (value: boolean) => void;
  setIsAwaitingAgent: (value: boolean) => void;
  setAgentReasoning: Dispatch<SetStateAction<string>>;
  setAgentDraft: Dispatch<SetStateAction<string>>;
  // The turn currently in flight, so the composer's Stop control can cancel
  // it. Null between turns; see useComposerFlags.
  turnAbortRef: RefObject<AbortController | null>;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  setError: (message: string | null) => void;
  // Documents already staged through /api/documents for this session:
  // the chat reads them each turn, and creating the run carries them
  // into its corpus. Files, not ids, would mean re-uploading.
  pendingAttachments: StagedDocument[];
  setPendingAttachments: Dispatch<SetStateAction<StagedDocument[]>>;
  setToast: ToastSetter;
  clearSessionState: () => void;
  stageDraftSpec: (
    spec: InferredRunSpec,
    createdAt?: number,
    intro?: DraftIntro,
  ) => void;
  focusComposer: () => void;
  reloadHistory: () => Promise<void>;
  onChatStarted: (chatId: string) => void;
  pubmedEnabled: boolean;
  webSearchEnabled: boolean;
}

/**
 * Sub-hook owning the spec lifecycle state machine: draftSpec (inferred from
 * the first submit, revisable by follow-up messages) -> confirmedSpec
 * (frozen at start) -> startedSession (the created+started run), plus the
 * transition helpers that only touch this state. Called unconditionally from
 * the top of useChatSession, so its hook call order stays fixed across
 * renders.
 */
function useLifecycleStages() {
  const [interview, setInterview] = useState<Interview | null>(null);
  const [draft, setDraft] = useState<SpecStage | null>(null);
  const [confirmed, setConfirmed] = useState<SpecStage | null>(null);
  const [startedSession, setStartedSession] = useState<StartedSession | null>(
    null,
  );
  return {
    interview,
    setInterview,
    draft,
    setDraft,
    confirmed,
    setConfirmed,
    startedSession,
    setStartedSession,
  };
}

export function useRunSpecLifecycle() {
  const stages = useLifecycleStages();
  const {setInterview, setDraft, setConfirmed, setStartedSession} = stages;

  // Drops all spec/session stages but keeps the message log; useCallback so
  // resetSession (which depends on it) also stays referentially stable.
  const clearSessionState = useCallback(() => {
    setDraft(null);
    setInterview(null);
    setConfirmed(null);
    setStartedSession(null);
  }, [setDraft, setInterview, setConfirmed, setStartedSession]);

  // Installs `spec` as the active draft and rolls back any later stages;
  // `intro` is the Agent's closing message, shown on the plan card.
  function stageDraftSpec(
    spec: InferredRunSpec,
    createdAt = Date.now() / 1000,
    intro?: DraftIntro,
  ) {
    const {message, reasoning, turnId, fallback} = intro ?? {};
    setDraft({spec, createdAt, intro: message, reasoning, turnId, fallback});
    setConfirmed(null);
    setStartedSession(null);
  }

  return {...stages, clearSessionState, stageDraftSpec};
}

/**
 * Sub-hook owning the composer's own state: the input text, the in-flight
 * flag, the chat log, and the last error, plus the full-session reset. Takes
 * `clearSessionState` (from {@link useRunSpecLifecycle}) as an argument since
 * resetSession has to wipe both slices together.
 */
function useComposerFlags() {
  // True while the create+start round trip is in flight; the view uses it to
  // disable the Start control against double submission.
  const [isStarting, setIsStarting] = useState(false);
  // True while awaiting the Agent's reply to an interview turn; drives the
  // thinking indicator in the chat timeline. Kept separate from isStarting
  // (which also covers the run create+start round trip).
  const [isAwaitingAgent, setIsAwaitingAgent] = useState(false);
  // The Agent's chain of thought for the turn in flight, accumulated from the
  // model's reasoning as it streams. Display-only and never persisted, so it
  // is cleared at the start of each turn rather than kept with the messages.
  const [agentReasoning, setAgentReasoning] = useState('');
  // The Agent's reply itself, accumulated as it streams. Display-only in the
  // same way: the turn's durable text arrives with the resolved interview and
  // replaces this, so it is cleared at the start of each turn.
  const [agentDraft, setAgentDraft] = useState('');
  // The in-flight turn's abort controller, so the composer's Stop control
  // can cancel whichever call is running (composer submit or a revision)
  // without the handler that started it having to hand back a reference.
  // A ref, not state: aborting must not wait for a render, and no view
  // reads this value directly.
  const turnAbortRef = useRef<AbortController | null>(null);
  return {
    isStarting,
    setIsStarting,
    isAwaitingAgent,
    setIsAwaitingAgent,
    agentReasoning,
    setAgentReasoning,
    agentDraft,
    setAgentDraft,
    turnAbortRef,
  };
}

export function useComposerLog(clearSessionState: () => void) {
  // Composer text; this stage feeds draftSpec on submit.
  const [input, setInput] = useState('');
  const flags = useComposerFlags();
  const {setIsStarting, setIsAwaitingAgent, setAgentReasoning} = flags;
  const {setAgentDraft, turnAbortRef} = flags;
  // Append-only log of user/assistant chat bubbles (spec cards are rendered
  // from the spec state, not stored here).
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<
    StagedDocument[]
  >([]);

  // Full wipe back to the pristine composer, used by "New chat"; stable
  // identity so callers can hang effects off it.
  const resetSession = useCallback(() => {
    // A turn left running into a reset would otherwise persist into a chat
    // the scientist has already navigated away from.
    turnAbortRef.current?.abort();
    turnAbortRef.current = null;
    clearSessionState();
    setInput('');
    setIsStarting(false);
    setIsAwaitingAgent(false);
    setAgentReasoning('');
    setAgentDraft('');
    setMessages([]);
    setError(null);
    setPendingAttachments([]);
  }, [
    clearSessionState,
    setIsStarting,
    setIsAwaitingAgent,
    setAgentReasoning,
    setAgentDraft,
    turnAbortRef,
  ]);

  return {
    input,
    setInput,
    ...flags,
    messages,
    setMessages,
    error,
    setError,
    pendingAttachments,
    setPendingAttachments,
    resetSession,
  };
}

/** Return shape of {@link useRunSpecLifecycle} (state + transition helpers). */
export type RunSpecLifecycle = ReturnType<typeof useRunSpecLifecycle>;

/** Return shape of {@link useComposerLog} (composer state + reset). */
export type ComposerLog = ReturnType<typeof useComposerLog>;

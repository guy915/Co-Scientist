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
import type {ToastSetter} from './timers';

export function useChatSession(deps: ChatSessionDeps) {
  const lifecycle = useRunSpecLifecycle();
  const composer = useComposerLog(lifecycle.clearSessionState);

  const hasConversation =
    composer.messages.length > 0 ||
    Boolean(lifecycle.interview) ||
    Boolean(lifecycle.draft) ||
    Boolean(lifecycle.confirmed) ||
    Boolean(lifecycle.startedSession);

  // Commit live dependencies in useLayoutEffect so aborted renders never leak;
  // stable handlers read that ref at call time without stale state.
  const handlerDepsBag = toHandlerDeps(lifecycle, composer, deps);
  const handlerDepsRef = useRef(handlerDepsBag);
  useLayoutEffect(() => {
    handlerDepsRef.current = handlerDepsBag;
  });
  const handlers = useMemo(
    () => buildChatHandlers(liveHandlerDeps(handlerDepsRef)),
    [],
  );

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

// Draft and confirmed stages carry their timestamp and closing turn as one value
// so transitions cannot split them.
export interface SpecStage {
  spec: InferredRunSpec;
  createdAt: number;
  intro?: string;
  reasoning?: string;
  // The plan card has no bubble; retain its durable closing-turn ID so retry
  // addresses the actual persisted answer.
  turnId?: number;
  fallback?: boolean;
}

export interface LinkedDraftRecovery {
  canContinueLinkedDraft: boolean;
  spec?: InferredRunSpec;
  status: 'checking' | 'error' | 'cancelled' | undefined;
  retryStatusLookup: () => void;
}

export interface DraftIntro {
  message?: string;
  reasoning?: string;
  turnId?: number;
  fallback?: boolean;
}

export interface ChatSessionDeps {
  reloadHistory: () => Promise<void>;
  // The first durable turn creates the routable chat ID; notify navigation only
  // once that identity exists.
  onChatStarted: (chatId: string) => void;
  focusComposer: () => void;
  setToast: ToastSetter;
  pubmedEnabled: boolean;
  webSearchEnabled: boolean;
}

// Freeze the whole completing turn across start, including its closing text,
// reasoning and fallback provenance.
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

export interface HandlerDeps {
  input: string;
  setInput: (value: string) => void;
  draft: SpecStage | null;
  interview: Interview | null;
  startedSession: StartedSession | null;
  setInterview: (interview: Interview | null) => void;
  setDraft: (stage: SpecStage | null) => void;
  setConfirmed: (stage: SpecStage | null) => void;
  // Stream fragments merge into current session state instead of replacing a
  // value captured before asynchronous progress.
  setStartedSession: Dispatch<SetStateAction<StartedSession | null>>;
  setIsStarting: (value: boolean) => void;
  setIsAwaitingAgent: (value: boolean) => void;
  setAgentReasoning: Dispatch<SetStateAction<string>>;
  setAgentDraft: Dispatch<SetStateAction<string>>;
  turnAbortRef: RefObject<AbortController | null>;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  setError: (message: string | null) => void;
  // Reuse staged IDs across interview and run creation; keeping Files instead
  // would re-upload attachments.
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

  const clearSessionState = useCallback(() => {
    setDraft(null);
    setInterview(null);
    setConfirmed(null);
    setStartedSession(null);
  }, [setDraft, setInterview, setConfirmed, setStartedSession]);

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

function useComposerFlags() {
  const [isStarting, setIsStarting] = useState(false);
  const [isAwaitingAgent, setIsAwaitingAgent] = useState(false);
  const [agentReasoning, setAgentReasoning] = useState('');
  const [agentDraft, setAgentDraft] = useState('');
  // Stop must abort immediately without waiting for render; the controller
  // belongs in a ref, not view state.
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
  const [input, setInput] = useState('');
  const flags = useComposerFlags();
  const {setIsStarting, setIsAwaitingAgent, setAgentReasoning} = flags;
  const {setAgentDraft, turnAbortRef} = flags;
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<
    StagedDocument[]
  >([]);

  const resetSession = useCallback(() => {
    // Reset cancels outstanding work before navigation so its result cannot
    // persist into the abandoned conversation.
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

export type RunSpecLifecycle = ReturnType<typeof useRunSpecLifecycle>;

export type ComposerLog = ReturnType<typeof useComposerLog>;

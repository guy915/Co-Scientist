import {type Dispatch, type SetStateAction} from 'react';
import {type InferredRunSpec} from '../run_spec';
import {type Interview} from '@/api/runs';
import {type Audience} from '../audience_context';
import {
  type ChatEntry,
  type StartedSession,
} from '../pages/chat_timeline_cards';
import {type ToastState} from './use_toast';

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
}

/** The Agent's closing turn, as staged onto the plan card. */
export interface DraftIntro {
  message?: string;
  reasoning?: string;
  turnId?: number;
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
  setToast: (value: string | ToastState | null) => void;
  pubmedEnabled: boolean;
  webSearchEnabled: boolean;
  paperCorpusEnabled: boolean;
  audience: Audience | null;
}

/**
 * Dependencies shared by `executeStart` and `startDraftRun`: the snapshotted
 * spec plus the relevant slice of `HandlerDeps` (callers pass the same
 * values they received there).
 */
export type ExecuteStartDeps = Pick<
  HandlerDeps,
  | 'pubmedEnabled'
  | 'webSearchEnabled'
  | 'paperCorpusEnabled'
  | 'reloadHistory'
  | 'setConfirmed'
  | 'setDraft'
  | 'setStartedSession'
  | 'setMessages'
  | 'pendingAttachments'
  | 'setPendingAttachments'
> & {
  specToStart: InferredRunSpec;
  specCreatedAt: number;
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
  setInterview: (interview: Interview | null) => void;
  setDraft: (stage: SpecStage | null) => void;
  setConfirmed: (stage: SpecStage | null) => void;
  setStartedSession: (session: StartedSession) => void;
  setIsStarting: (value: boolean) => void;
  setIsAwaitingAgent: (value: boolean) => void;
  setAgentReasoning: Dispatch<SetStateAction<string>>;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  setError: (message: string | null) => void;
  pendingAttachments: File[];
  setPendingAttachments: Dispatch<SetStateAction<File[]>>;
  setToast: (value: string | ToastState | null) => void;
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
  paperCorpusEnabled: boolean;
  audience: Audience | null;
}

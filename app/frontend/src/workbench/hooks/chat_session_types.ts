import {type Dispatch, type SetStateAction} from 'react';
import {type InferredRunSpec} from '../run_spec';
import {
  type ChatEntry,
  type StartedSession,
} from '../pages/chat_timeline_cards';
import {type ToastState} from './use_toast';

/** View-layer collaborators the session needs but does not own. */
export interface ChatSessionDeps {
  reloadHistory: () => Promise<void>;
  focusComposer: () => void;
  setToast: (value: string | ToastState | null) => void;
  pubmedEnabled: boolean;
}

/** Dependencies shared by `executeStart` and `startDraftRun`. */
export interface ExecuteStartDeps {
  specToStart: InferredRunSpec;
  specCreatedAt: number;
  pubmedEnabled: boolean;
  reloadHistory: () => Promise<void>;
  setConfirmedSpec: (spec: InferredRunSpec) => void;
  setConfirmedSpecCreatedAt: (createdAt: number) => void;
  setDraftSpec: (spec: InferredRunSpec | null) => void;
  setDraftSpecCreatedAt: (createdAt: number | null) => void;
  setStartedSession: (session: StartedSession) => void;
}

/**
 * Every value/setter the module-level handler functions might need; each
 * handler passes this (optionally merged with a per-call value like `message`)
 * so it only has to name what it actually uses.
 */
export interface HandlerDeps {
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

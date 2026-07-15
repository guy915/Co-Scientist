import {type Dispatch, type SetStateAction} from 'react';
import {type InferredRunSpec} from '../run_spec';
import {type Interview} from '@/api/runs';
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
}

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
  setConfirmed: (stage: SpecStage | null) => void;
  setDraft: (stage: SpecStage | null) => void;
  setStartedSession: (session: StartedSession) => void;
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  pendingAttachments: File[];
  setPendingAttachments: (files: File[]) => void;
}

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
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>;
  setError: (message: string | null) => void;
  pendingAttachments: File[];
  setPendingAttachments: Dispatch<SetStateAction<File[]>>;
  setToast: (value: string | ToastState | null) => void;
  clearSessionState: () => void;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
  focusComposer: () => void;
  reloadHistory: () => Promise<void>;
  pubmedEnabled: boolean;
}

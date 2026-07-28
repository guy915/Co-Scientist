import {useCallback, useState} from 'react';
import {type Interview} from '@/api/runs';
import {type InferredRunSpec} from '../run_spec';
import {
  type ChatEntry,
  type StartedSession,
} from '../pages/chat_timeline_cards';
import {type DraftIntro, type SpecStage} from './chat_session_types';

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
    setDraft({
      spec,
      createdAt,
      intro: intro?.message,
      reasoning: intro?.reasoning,
    });
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
  return {
    isStarting,
    setIsStarting,
    isAwaitingAgent,
    setIsAwaitingAgent,
    agentReasoning,
    setAgentReasoning,
  };
}

export function useComposerLog(clearSessionState: () => void) {
  // Composer text; this stage feeds draftSpec on submit.
  const [input, setInput] = useState('');
  const flags = useComposerFlags();
  const {setIsStarting, setIsAwaitingAgent, setAgentReasoning} = flags;
  // Append-only log of user/assistant chat bubbles (spec cards are rendered
  // from the spec state, not stored here).
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<File[]>([]);

  // Full wipe back to the pristine composer, used by "New chat"; stable
  // identity so callers can hang effects off it.
  const resetSession = useCallback(() => {
    clearSessionState();
    setInput('');
    setIsStarting(false);
    setIsAwaitingAgent(false);
    setAgentReasoning('');
    setMessages([]);
    setError(null);
    setPendingAttachments([]);
  }, [clearSessionState, setIsStarting, setIsAwaitingAgent, setAgentReasoning]);

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

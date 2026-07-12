import {useCallback, useState} from 'react';
import {type Interview} from '@/api/runs';
import {type InferredRunSpec} from '../run_spec';
import {
  type ChatEntry,
  type StartedSession,
} from '../pages/chat_timeline_cards';
import {type SpecStage} from './chat_session_types';

/**
 * Sub-hook owning the spec lifecycle state machine: draftSpec (inferred from
 * the first submit, revisable by follow-up messages) -> confirmedSpec
 * (frozen at start) -> startedSession (the created+started run), plus the
 * transition helpers that only touch this state. Called unconditionally from
 * the top of useChatSession, so its hook call order stays fixed across
 * renders.
 */
export function useRunSpecLifecycle() {
  const [interview, setInterview] = useState<Interview | null>(null);
  const [draft, setDraft] = useState<SpecStage | null>(null);
  const [confirmed, setConfirmed] = useState<SpecStage | null>(null);
  const [startedSession, setStartedSession] = useState<StartedSession | null>(
    null,
  );

  // Drops all spec/session stages but keeps the message log; useCallback so
  // resetSession (which depends on it) also stays referentially stable.
  const clearSessionState = useCallback(() => {
    setDraft(null);
    setInterview(null);
    setConfirmed(null);
    setStartedSession(null);
  }, []);

  // Installs `spec` as the active draft and rolls back any later stages
  // (confirmed/started), since a new draft restarts the lifecycle.
  function stageDraftSpec(
    spec: InferredRunSpec,
    createdAt = Date.now() / 1000,
  ) {
    setDraft({spec, createdAt});
    setConfirmed(null);
    setStartedSession(null);
  }

  return {
    draft,
    interview,
    setInterview,
    setDraft,
    confirmed,
    setConfirmed,
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
export function useComposerLog(clearSessionState: () => void) {
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

/** Return shape of {@link useRunSpecLifecycle} (state + transition helpers). */
export type RunSpecLifecycle = ReturnType<typeof useRunSpecLifecycle>;

/** Return shape of {@link useComposerLog} (composer state + reset). */
export type ComposerLog = ReturnType<typeof useComposerLog>;

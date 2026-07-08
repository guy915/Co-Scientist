import {type FormEvent, useCallback, useState} from 'react';
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

/**
 * Owns the chat workspace's session state machine: the composer input, the
 * message log, the draft/confirmed run specs, and the started session, plus
 * every handler that transitions between them. View concerns (history reload,
 * composer focus, toasts) are injected via {@link ChatSessionDeps}.
 */
export function useChatSession({
  reloadHistory,
  focusComposer,
  setToast,
  pubmedEnabled,
}: ChatSessionDeps) {
  const [input, setInput] = useState('');
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
  const [isStarting, setIsStarting] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const hasConversation =
    messages.length > 0 ||
    Boolean(draftSpec) ||
    Boolean(confirmedSpec) ||
    Boolean(startedSession);

  function appendAssistant(content: string, createdAt = Date.now() / 1000) {
    setMessages(prev => [
      ...prev,
      {
        id: makePrefixedId('assistant'),
        role: 'assistant',
        content,
        created_at: createdAt,
      },
    ]);
    return createdAt;
  }

  function appendUser(content: string, createdAt = Date.now() / 1000) {
    setMessages(prev => [
      ...prev,
      {
        id: makePrefixedId('user'),
        role: 'user',
        content,
        created_at: createdAt,
      },
    ]);
    return createdAt;
  }

  const clearSessionState = useCallback(() => {
    setDraftSpec(null);
    setDraftSpecCreatedAt(null);
    setConfirmedSpec(null);
    setConfirmedSpecCreatedAt(null);
    setStartedSession(null);
  }, []);

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

  const resetSession = useCallback(() => {
    clearSessionState();
    setInput('');
    setIsStarting(false);
    setMessages([]);
    setError(null);
  }, [clearSessionState]);

  function handleRetryMessage(message: ChatEntry) {
    appendAssistant(message.content);
  }

  function handleEditMessage(message: ChatEntry) {
    setInput(message.content);
    focusComposer();
  }

  async function handleCopyRequest(message: ChatEntry) {
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

  function handleRetryDraftSpec() {
    if (!draftSpec) return;
    stageDraftSpec(inferRunSpec(draftSpec.goal));
  }

  function handleCancelDraftSpec() {
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

  function handleEditPlan(spec: InferredRunSpec) {
    stageDraftSpec(spec);
    focusComposer();
    emitDiagnosticEvent({
      stage: 'CHAT',
      run: referenceSetupTitle(spec.goal),
      payload: {event: 'plan_edit_requested'},
    });
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput('');
    setError(null);
    setToast(null);

    if (draftSpec) {
      const sentAt = appendUser(text);
      const next = reviseRunSpec(draftSpec, text);
      stageDraftSpec(next, sentAt + 0.001);
      appendAssistant(
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

    const sentAt = appendUser(text);
    const next = inferRunSpec(text);
    stageDraftSpec(next, sentAt + 0.001);
    emitDiagnosticEvent({
      stage: 'LIFECYCLE',
      run: referenceSetupTitle(next.goal),
      payload: {event: 'draft_created'},
    });
  }

  async function handleStartRun() {
    if (!draftSpec) return;
    const specToStart = draftSpec;
    const specCreatedAt = draftSpecCreatedAt ?? Date.now() / 1000;
    setIsStarting(true);
    setError(null);
    setToast(null);
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
    } finally {
      setIsStarting(false);
    }
  }

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

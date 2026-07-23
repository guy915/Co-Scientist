import {useLayoutEffect, useMemo, useRef} from 'react';
import {useComposerLog, useRunSpecLifecycle} from './chat_session_state';
import {buildChatHandlers, toHandlerDeps} from './chat_session_handlers';
import {liveHandlerDeps} from './chat_session_helpers';
import {type ChatSessionDeps} from './chat_session_types';

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
    startedSession: lifecycle.startedSession,
    setStartedSession: lifecycle.setStartedSession,
    isStarting: composer.isStarting,
    isAwaitingAgent: composer.isAwaitingAgent,
    agentReasoning: composer.agentReasoning,
    messages: composer.messages,
    error: composer.error,
    hasConversation,
    resetSession: composer.resetSession,
    stageDraftSpec: lifecycle.stageDraftSpec,
    ...handlers,
  };
}

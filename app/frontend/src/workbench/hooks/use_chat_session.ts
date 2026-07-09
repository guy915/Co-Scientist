import {useComposerLog, useRunSpecLifecycle} from './chat_session_state';
import {buildChatHandlers, toHandlerDeps} from './chat_session_handlers';
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
    Boolean(lifecycle.draftSpec) ||
    Boolean(lifecycle.confirmedSpec) ||
    Boolean(lifecycle.startedSession);

  const handlers = buildChatHandlers(toHandlerDeps(lifecycle, composer, deps));

  // Exposed surface: raw state + setters for the view to render the
  // timeline, and the handler set that encodes every legal transition.
  return {
    input: composer.input,
    setInput: composer.setInput,
    draftSpec: lifecycle.draftSpec,
    setDraftSpec: lifecycle.setDraftSpec,
    draftSpecCreatedAt: lifecycle.draftSpecCreatedAt,
    confirmedSpec: lifecycle.confirmedSpec,
    confirmedSpecCreatedAt: lifecycle.confirmedSpecCreatedAt,
    startedSession: lifecycle.startedSession,
    setStartedSession: lifecycle.setStartedSession,
    isStarting: composer.isStarting,
    messages: composer.messages,
    error: composer.error,
    hasConversation,
    resetSession: composer.resetSession,
    stageDraftSpec: lifecycle.stageDraftSpec,
    ...handlers,
  };
}

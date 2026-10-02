import {lazy, Suspense, useCallback, useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {useLocation, useNavigate, useParams} from 'react-router-dom';
import {conciseTitle} from '@/lib/text';
import {HEADER_TITLE_EVENT, NEW_CHAT_EVENT} from '../dom_events';
import {useToast, type ToastState} from '../hooks/use_toast';
import {useRunHistoryContext} from '../hooks/run_history_context';
import {useChatSession} from '../hooks/use_chat_session';
import {useChatRehydration} from '../hooks/use_chat_rehydrate';
import {type SpecStage} from '../hooks/chat_session_types';
import {type ConnectorToggleProps} from './chat_composer_connectors';
import {HomeStage} from './chat_home_stage';

// The landing page under the home stage, split into its own chunk so the
// chat home's first paint does not wait on it.
const HomeLanding = lazy(() => import('./home_landing'));
import {type StartedSession} from './chat_timeline_started_card';
import {
  ConversationView,
  useConversationLayout,
} from './chat_workspace_conversation';

interface ChatWorkspaceLocationState {
  cosciAction?: 'new-chat' | 'focus-composer';
}

export function ChatWorkspace() {
  const navigate = useNavigate();
  const {id: chatId} = useParams<{id?: string}>();
  const [showAllRecents, setShowAllRecents] = useState(false);
  const [pubmedEnabled, setPubmedEnabled] = useState(true);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const connectors: ConnectorToggleProps = {
    pubmedEnabled,
    onPubmedEnabledChange: setPubmedEnabled,
    webSearchEnabled,
    onWebSearchEnabledChange: setWebSearchEnabled,
  };
  const {toast, setToast} = useToast();
  const {history, reload: reloadHistory} = useRunHistoryContext();
  const onChatStarted = useCallback(
    (id: string) => void navigate(`/chats/${id}`, {replace: true}),
    [navigate],
  );
  const session = useChatSession({
    reloadHistory,
    focusComposer: focusComposerTextarea,
    onChatStarted,
    setToast,
    pubmedEnabled,
    webSearchEnabled,
  });
  const linkedDraftRecovery = useChatRehydration(session, chatId);
  const resetWorkspace = useCallback(() => {
    session.resetSession();
    setToast(null);
    void reloadHistory();
  }, [reloadHistory, session.resetSession, setToast]);
  useChatWorkspaceGlobalEvents({
    resetWorkspace,
    focusComposer: focusComposerTextarea,
  });
  useEffect(
    () => syncHeaderTitle(session.draft, session.startedSession),
    [session.draft, session.startedSession],
  );
  const {timelineItems, scrollRef, composerRef} = useConversationLayout(
    session,
    navigate,
    resetWorkspace,
    focusComposerTextarea,
    linkedDraftRecovery,
  );

  return (
    <div className="reference-workspace">
      <main className="reference-workspace-main">
        {session.hasConversation ? (
          <ConversationView
            scrollRef={scrollRef}
            timelineItems={timelineItems}
            composerRef={composerRef}
            session={session}
            setupDraftMode={Boolean(session.draft || session.startedSession)}
            connectors={connectors}
          />
        ) : (
          <>
            <HomeStage
              input={session.input}
              setInput={session.setInput}
              connectors={connectors}
              onSubmit={session.handleSubmit}
              runs={history}
              showAllRecents={showAllRecents}
              onToggleShowAll={() => setShowAllRecents(current => !current)}
            />
            <Suspense fallback={null}>
              <HomeLanding />
            </Suspense>
          </>
        )}
        <ToastPortal toast={toast} />
      </main>
    </div>
  );
}

// Effect body for `focusComposer` above: focuses the composer textarea on
// the next animation frame.
function focusComposerTextarea() {
  window.requestAnimationFrame(() => {
    const composer = document.querySelector<HTMLTextAreaElement>(
      '.reference-composer textarea',
    );
    composer?.focus();
  });
}

// Effect body for the header-title sync above: dispatches the current draft/
// started title to the app shell header; the returned cleanup clears it back
// to empty on unmount or before the next run.
function syncHeaderTitle(
  draft: SpecStage | null,
  startedSession: StartedSession | null,
) {
  const title = draft
    ? conciseTitle(draft.spec.goal)
    : startedSession
      ? startedSession.title
      : '';
  window.dispatchEvent(new CustomEvent(HEADER_TITLE_EVENT, {detail: title}));
  return () => {
    window.dispatchEvent(new CustomEvent(HEADER_TITLE_EVENT, {detail: ''}));
  };
}

// Keep the toast above ancestor stacking contexts.
function ToastPortal({toast}: {toast: ToastState | null}) {
  if (!toast) return null;
  return createPortal(
    <div
      className="reference-toast fixed bottom-4 left-4 z-[80] flex items-center gap-4 rounded-xl bg-cosci-toast-bg px-4 py-[0.7rem] text-[0.92rem] font-medium text-cosci-toast-fg"
      role="status"
    >
      <span>{toast.message}</span>
      {toast.action && (
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent p-0 font-[inherit] text-[0.92rem] font-medium text-cosci-toast-action focus-visible:outline-none focus-visible:underline"
          onClick={toast.action.onClick}
        >
          {toast.action.label}
        </button>
      )}
    </div>,
    document.body,
  );
}

// Listens for the nav rail's global "new chat" custom event, which fires
// outside React's tree (e.g. from the app shell header), and handles the
// new-chat/focus-composer actions when they arrive as router navigation
// state instead (see ChatWorkspaceLocationState), clearing that state so it
// doesn't re-fire on a later re-render or back/forward navigation.
function useChatWorkspaceGlobalEvents({
  resetWorkspace,
  focusComposer,
}: {
  resetWorkspace: () => void;
  focusComposer: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    window.addEventListener(NEW_CHAT_EVENT, resetWorkspace);
    return () => {
      window.removeEventListener(NEW_CHAT_EVENT, resetWorkspace);
    };
  }, [resetWorkspace]);

  useEffect(() => {
    const state = location.state as ChatWorkspaceLocationState | null;
    if (!state?.cosciAction) return;
    if (state.cosciAction === 'new-chat') resetWorkspace();
    if (state.cosciAction === 'focus-composer') focusComposer();
    void navigate(location.pathname, {replace: true, state: null});
  }, [
    focusComposer,
    location.pathname,
    location.state,
    navigate,
    resetWorkspace,
  ]);
}

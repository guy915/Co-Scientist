import {useCallback, useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {useLocation, useNavigate} from 'react-router-dom';
import {conciseTitle} from '@/lib/text';
import {useToast, type ToastState} from '../hooks/use_toast';
import {useRunHistory} from '../hooks/use_run_history';
import {useChatSession} from '../hooks/use_chat_session';
import {type SpecStage} from '../hooks/chat_session_types';
import {
  HOME_TOAST_ACTION_CLASSES,
  HOME_TOAST_CLASSES,
  HOME_WORKSPACE_CLASSES,
  HOME_WORKSPACE_MAIN_CLASSES,
} from './chat_home_classes';
import {HomeStage} from './chat_home_stage';
import {type StartedSession} from './chat_timeline_cards';
import {
  ConversationView,
  useConversationLayout,
} from './chat_workspace_conversation';

// Cross-route signal carried on react-router navigation state (see the nav
// rail's "New chat" / focus-composer actions) so this page can react to an
// action that originated outside it.
interface ChatWorkspaceLocationState {
  cosciAction?: 'new-chat' | 'focus-composer';
}

/**
 * Renders the chat-first Co-Scientist workspace.
 *
 * Orchestrates the page: owns view-only UI state (recents expansion, PubMed
 * toggle, scroll/composer refs), delegates the actual session state machine
 * (messages, draft/confirmed run spec, started session) to useChatSession,
 * merges everything into a single sorted timeline, and renders either the
 * session-home stage (HomeStage) or the in-conversation timeline + composer
 * (ConversationView).
 */
export function ChatWorkspace() {
  const navigate = useNavigate();
  // Recents list on the home stage is capped by default; this expands it.
  const [showAllRecents, setShowAllRecents] = useState(false);
  // PubMed connector toggle, shared between the home and in-chat composer.
  const [pubmedEnabled, setPubmedEnabled] = useState(true);

  const {toast, setToast} = useToast();
  const {history, homeScores, reloadHistory} = useRunHistory();

  // Focuses the composer textarea on the next frame; used both locally and
  // injected into useChatSession.
  const focusComposer = useCallback(focusComposerTextarea, []);

  // The session state machine lives entirely in this hook; fields used once
  // below are read straight off `session`, and the three read more than once
  // (draft/startedSession/hasConversation) are destructured for brevity.
  const session = useChatSession({
    reloadHistory,
    focusComposer,
    setToast,
    pubmedEnabled,
  });
  const {draft, startedSession, hasConversation} = session;

  // Clears the session back to the empty home stage and refreshes recents,
  // so "New chat" also picks up any run that just finished elsewhere.
  const resetWorkspace = useCallback(() => {
    session.resetSession();
    setToast(null);
    void reloadHistory();
  }, [reloadHistory, session.resetSession, setToast]);

  // Wires the nav rail's global "new chat" / "focus composer" actions into
  // the handlers above.
  useChatWorkspaceGlobalEvents({resetWorkspace, focusComposer});

  // Publishes the current draft/started title as the app shell's header via
  // a custom event, since the header lives outside this subtree.
  useEffect(
    () => syncHeaderTitle(draft, startedSession),
    [draft, startedSession],
  );

  // Timeline items, its auto-scroll ref, and the composer ref whose measured
  // height feeds the timeline's bottom padding all live together in one
  // layout hook (see useConversationLayout).
  const {timelineItems, scrollRef, composerRef} = useConversationLayout(
    session,
    navigate,
    resetWorkspace,
    focusComposer,
  );

  return (
    <div className={HOME_WORKSPACE_CLASSES}>
      <main className={HOME_WORKSPACE_MAIN_CLASSES}>
        {/* No conversation yet: session-home stage. Otherwise: timeline. */}
        {!hasConversation ? (
          <HomeStage
            input={session.input}
            setInput={session.setInput}
            pubmedEnabled={pubmedEnabled}
            onPubmedEnabledChange={setPubmedEnabled}
            onSubmit={session.handleSubmit}
            runs={history}
            scoresByRunId={homeScores}
            showAllRecents={showAllRecents}
            onToggleShowAll={() => setShowAllRecents(current => !current)}
          />
        ) : (
          <ConversationView
            scrollRef={scrollRef}
            timelineItems={timelineItems}
            composerRef={composerRef}
            session={session}
            setupDraftMode={Boolean(draft || startedSession)}
            pubmedEnabled={pubmedEnabled}
            onPubmedEnabledChange={setPubmedEnabled}
          />
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
  window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: title}));
  return () => {
    window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
  };
}

// Toast is portaled to <body> so no ancestor stacking context can trap it;
// see HOME_TOAST_CLASSES for the fixed-position styling. Renders nothing
// when there is no toast to show.
function ToastPortal({toast}: {toast: ToastState | null}) {
  if (!toast) return null;
  return createPortal(
    <div className={HOME_TOAST_CLASSES} role="status">
      <span>{toast.message}</span>
      {toast.action && (
        <button
          type="button"
          className={HOME_TOAST_ACTION_CLASSES}
          onClick={toast.action.onClick}
        >
          {toast.action.label}
        </button>
      )}
    </div>,
    document.body,
  );
}

// Listens for the nav rail's global "new chat" / "focus composer" custom
// events, which fire outside React's tree (e.g. from the app shell header),
// and handles the same two actions when they arrive as router navigation
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
    window.addEventListener('cosci-new-chat', resetWorkspace);
    window.addEventListener('cosci-focus-composer', focusComposer);
    return () => {
      window.removeEventListener('cosci-new-chat', resetWorkspace);
      window.removeEventListener('cosci-focus-composer', focusComposer);
    };
  }, [focusComposer, resetWorkspace]);

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

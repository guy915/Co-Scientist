import {type RefObject, useCallback, useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {
  type NavigateFunction,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom';
import {type Run} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {HEADER_TITLE_EVENT, NEW_CHAT_EVENT} from '../dom_events';
import {useToast, type ToastState} from '../hooks/use_toast';
import {useRunHistory} from '../hooks/use_run_history';
import {useChatSession} from '../hooks/use_chat_session';
import {useChatRehydration} from '../hooks/use_chat_rehydrate';
import {type SpecStage} from '../hooks/chat_session_types';
import {
  HOME_TOAST_ACTION_CLASSES,
  HOME_TOAST_CLASSES,
  HOME_WORKSPACE_CLASSES,
  HOME_WORKSPACE_MAIN_CLASSES,
} from './chat_home_classes';
import {type ConnectorToggleProps} from './chat_composer_connectors';
import {HomeStage} from './chat_home_stage';
import {type StartedSession} from './chat_timeline_cards';
import {type TimelineItem} from './chat_workspace_timeline';
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

// useToast's setter type, matching its actual (non-Dispatch) signature.
type SetToast = (value: string | ToastState | null) => void;

// Owns the PubMed/web-search connector toggles, each defaulting on and
// shared between the home and in-chat composers. Returned in the shape the
// composer already takes them in (ConnectorToggleProps), so every surface
// between here and the connectors menu passes one value rather than
// restating the same four names.
function useConnectorToggles(): ConnectorToggleProps {
  const [pubmedEnabled, setPubmedEnabled] = useState(true);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  return {
    pubmedEnabled,
    onPubmedEnabledChange: setPubmedEnabled,
    webSearchEnabled,
    onWebSearchEnabledChange: setWebSearchEnabled,
  };
}

// Everything ChatWorkspace needs from the session state machine plus the
// data feeding the toast and recents panel, bundled so the two workspace
// hooks below can be composed with a single argument each.
interface WorkspaceSessionBundle {
  toast: ToastState | null;
  setToast: SetToast;
  history: Run[];
  homeScores: Record<string, number | null>;
  reloadHistory: () => Promise<void>;
  focusComposer: () => void;
  session: ReturnType<typeof useChatSession>;
}

// Owns the toast, recents-history, and session state machine, and the
// stable focusComposer callback they all share.
function useWorkspaceSessionBundle(
  connectors: ConnectorToggleProps,
): WorkspaceSessionBundle {
  const {toast, setToast} = useToast();
  const {history, homeScores, reloadHistory} = useRunHistory();
  const navigate = useNavigate();
  // Focuses the composer textarea on the next frame; used both locally and
  // injected into useChatSession. A module-level function is already stable
  // across renders, so it needs no useCallback to be a safe effect dep.
  const focusComposer = focusComposerTextarea;
  // A conversation gets its durable id from its first turn; putting it in the
  // URL there is what makes reloading (or reopening from the rail) return to
  // this chat rather than a blank workspace. Replace, not push: the blank
  // workspace is not a step worth going back to.
  const onChatStarted = useCallback(
    (chatId: string) => {
      void navigate(`/chats/${chatId}`, {replace: true});
    },
    [navigate],
  );
  const session = useChatSession({
    reloadHistory,
    focusComposer,
    onChatStarted,
    setToast,
    pubmedEnabled: connectors.pubmedEnabled,
    webSearchEnabled: connectors.webSearchEnabled,
  });
  return {
    toast,
    setToast,
    history,
    homeScores,
    reloadHistory,
    focusComposer,
    session,
  };
}

// Clears the session back to the empty home stage and refreshes recents, so
// "New chat" also picks up any run that just finished elsewhere.
function useResetWorkspace(
  session: ReturnType<typeof useChatSession>,
  setToast: SetToast,
  reloadHistory: () => Promise<void>,
): () => void {
  return useCallback(() => {
    session.resetSession();
    setToast(null);
    void reloadHistory();
  }, [reloadHistory, session.resetSession, setToast]);
}

// Publishes the current draft/started title as the app shell's header via a
// custom event, since the header lives outside this subtree.
function useSyncHeaderTitle(
  draft: SpecStage | null,
  startedSession: StartedSession | null,
) {
  useEffect(
    () => syncHeaderTitle(draft, startedSession),
    [draft, startedSession],
  );
}

// Wires up "New chat"/header-title sync and builds the timeline layout, once
// the session bundle above exists. Split from useWorkspaceSessionBundle so
// each hook stays focused and short; both are only ever called together, in
// this order, from ChatWorkspace.
function useWorkspaceLayoutBundle(
  sessionBundle: WorkspaceSessionBundle,
  navigate: NavigateFunction,
) {
  const {session, setToast, reloadHistory, focusComposer} = sessionBundle;
  const {draft, startedSession} = session;
  const resetWorkspace = useResetWorkspace(session, setToast, reloadHistory);
  // Wires the nav rail's global "new chat" / "focus composer" actions into
  // the handlers above.
  useChatWorkspaceGlobalEvents({resetWorkspace, focusComposer});
  useSyncHeaderTitle(draft, startedSession);
  // Timeline items, its auto-scroll ref, and the composer ref whose measured
  // height feeds the timeline's bottom padding all live together in one
  // layout hook (see useConversationLayout).
  const {timelineItems, scrollRef, composerRef} = useConversationLayout(
    session,
    navigate,
    resetWorkspace,
    focusComposer,
  );
  return {timelineItems, scrollRef, composerRef};
}

/**
 * Renders the chat-first Co-Scientist workspace.
 *
 * Orchestrates the page: owns view-only UI state (recents expansion,
 * connector toggles), delegates the actual session state machine (messages,
 * draft/confirmed run spec, started session) to useChatSession, merges
 * everything into a single sorted timeline, and renders either the
 * session-home stage (HomeStage) or the in-conversation timeline + composer
 * (ConversationView) via WorkspaceMain.
 */
export function ChatWorkspace() {
  const navigate = useNavigate();
  // Present on /chats/:id, absent on "/" (a chat that has not started yet).
  const {id: chatId} = useParams<{id?: string}>();
  // Recents list on the home stage is capped by default; this expands it.
  const [showAllRecents, setShowAllRecents] = useState(false);
  const connectors = useConnectorToggles();

  // The session state machine, toast, and recents data all live in
  // this bundle; the layout bundle below wires "New chat"/header-title sync
  // and builds the timeline on top of it.
  const sessionBundle = useWorkspaceSessionBundle(connectors);
  const {session, toast, history, homeScores} = sessionBundle;
  useChatRehydration(session, chatId);
  const {timelineItems, scrollRef, composerRef} = useWorkspaceLayoutBundle(
    sessionBundle,
    navigate,
  );

  return (
    <div className={HOME_WORKSPACE_CLASSES}>
      <main className={HOME_WORKSPACE_MAIN_CLASSES}>
        <WorkspaceMain
          hasConversation={session.hasConversation}
          session={session}
          connectors={connectors}
          recents={{
            history,
            homeScores,
            showAllRecents,
            onToggleShowAll: () => setShowAllRecents(current => !current),
          }}
          layout={{scrollRef, timelineItems, composerRef}}
        />
        <ToastPortal toast={toast} />
      </main>
    </div>
  );
}

// Recents-panel data/handlers passed through to HomeStage.
interface WorkspaceRecents {
  history: Run[];
  homeScores: Record<string, number | null>;
  showAllRecents: boolean;
  onToggleShowAll: () => void;
}

// Timeline layout refs/items passed through to ConversationView.
interface WorkspaceLayout {
  scrollRef: RefObject<HTMLDivElement | null>;
  timelineItems: TimelineItem[];
  composerRef: RefObject<HTMLDivElement | null>;
}

// The session-home stage, rendered while there's no conversation yet.
function HomeStageSection({
  session,
  connectors,
  recents,
}: {
  session: ReturnType<typeof useChatSession>;
  connectors: ConnectorToggleProps;
  recents: WorkspaceRecents;
}) {
  return (
    <HomeStage
      input={session.input}
      setInput={session.setInput}
      connectors={connectors}
      onSubmit={session.handleSubmit}
      runs={recents.history}
      scoresByRunId={recents.homeScores}
      showAllRecents={recents.showAllRecents}
      onToggleShowAll={recents.onToggleShowAll}
    />
  );
}

// The in-conversation timeline + composer, rendered once a conversation has
// started.
function ConversationSection({
  session,
  connectors,
  layout,
}: {
  session: ReturnType<typeof useChatSession>;
  connectors: ConnectorToggleProps;
  layout: WorkspaceLayout;
}) {
  return (
    <ConversationView
      scrollRef={layout.scrollRef}
      timelineItems={layout.timelineItems}
      composerRef={layout.composerRef}
      session={session}
      setupDraftMode={Boolean(session.draft || session.startedSession)}
      connectors={connectors}
    />
  );
}

// No conversation yet: session-home stage. Otherwise: the in-conversation
// timeline + composer. Split out of ChatWorkspace as a pure render
// component so the parent's hook wiring stays readable on its own.
function WorkspaceMain({
  hasConversation,
  session,
  connectors,
  recents,
  layout,
}: {
  hasConversation: boolean;
  session: ReturnType<typeof useChatSession>;
  connectors: ConnectorToggleProps;
  recents: WorkspaceRecents;
  layout: WorkspaceLayout;
}) {
  if (!hasConversation) {
    return (
      <HomeStageSection
        session={session}
        connectors={connectors}
        recents={recents}
      />
    );
  }
  return (
    <ConversationSection
      session={session}
      connectors={connectors}
      layout={layout}
    />
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

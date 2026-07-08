import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {createPortal} from 'react-dom';
import {useLocation, useNavigate} from 'react-router-dom';
import {conciseTitle} from '@/lib/text';
import {useToast} from '../hooks/use_toast';
import {useRunHistory} from '../hooks/use_run_history';
import {useChatSession} from '../hooks/use_chat_session';
import {
  HOME_TOAST_ACTION_CLASSES,
  HOME_TOAST_CLASSES,
  HOME_WORKSPACE_CLASSES,
  HOME_WORKSPACE_MAIN_CLASSES,
} from './chat_home_classes';
import {
  CHAT_COLUMN_CLASSES,
  CHAT_COMPOSER_CLASSES,
  CHAT_TIMELINE_CLASSES,
} from './chat_setup_classes';
import {Composer} from './chat_composer';
import {HomeStage} from './chat_home_stage';
import {
  ChatBubble,
  RunSpecCard,
  StartedSessionCard,
} from './chat_timeline_cards';

// One renderable entry in the chat timeline. Local chat messages, the
// draft/confirmed run-spec cards, and the started-session card are all
// normalized into this shape so they can be merged and sorted by time.
interface TimelineItem {
  id: string;
  at: number;
  order: number;
  node: ReactNode;
}

// Cross-route signal carried on react-router navigation state (see the nav
// rail's "New chat" / focus-composer actions) so this page can react to an
// action that originated outside it.
type ChatWorkspaceLocationState = {
  cosciAction?: 'new-chat' | 'focus-composer';
};

/**
 * Renders the chat-first Co-Scientist workspace.
 *
 * Orchestrates the page: owns view-only UI state (recents expansion, PubMed
 * toggle, scroll/composer refs), delegates the actual session state machine
 * (messages, draft/confirmed run spec, started session) to useChatSession,
 * merges everything into a single sorted timeline, and renders either the
 * session-home stage (HomeStage) or the in-conversation timeline + composer.
 */
export function ChatWorkspace() {
  const location = useLocation();
  const navigate = useNavigate();
  // Recents list on the home stage is capped by default; this expands it.
  const [showAllRecents, setShowAllRecents] = useState(false);
  // PubMed connector toggle, shared between the home and in-chat composer.
  const [pubmedEnabled, setPubmedEnabled] = useState(true);
  // Scrollable timeline container; scrollTop is driven imperatively below.
  const scrollRef = useRef<HTMLDivElement>(null);
  // Wraps the overlaid composer; its measured height feeds the timeline's
  // bottom padding via a CSS custom property (see the ResizeObserver effect).
  const composerRef = useRef<HTMLDivElement>(null);
  // Last timeline signature we auto-scrolled for, so the scroll effect only
  // fires when the timeline actually changed shape/order.
  const previousTimelineSignature = useRef('');

  const {toast, setToast} = useToast();
  const {history, homeScores, reloadHistory} = useRunHistory();

  // Focuses the composer textarea on the next frame (after it has mounted /
  // become visible), used both locally and injected into useChatSession.
  const focusComposer = useCallback(() => {
    window.requestAnimationFrame(() => {
      const composer = document.querySelector<HTMLTextAreaElement>(
        '.reference-composer textarea',
      );
      composer?.focus();
    });
  }, []);

  // The session state machine (composer input, message log, draft/confirmed
  // run spec, started session, and their handlers) lives entirely in this
  // hook; this component only reads it to build the timeline and render it.
  const session = useChatSession({
    reloadHistory,
    focusComposer,
    setToast,
    pubmedEnabled,
  });
  const {
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
  } = session;

  // Clears the session back to the empty home stage and refreshes the
  // recents list, so a fresh "New chat" also picks up any run that just
  // finished elsewhere.
  const resetWorkspace = useCallback(() => {
    resetSession();
    setToast(null);
    void reloadHistory();
  }, [reloadHistory, resetSession, setToast]);

  // Listens for the nav rail's global "new chat" / "focus composer" custom
  // events, which fire outside React's tree (e.g. from the app shell header).
  useEffect(() => {
    window.addEventListener('cosci-new-chat', resetWorkspace);
    window.addEventListener('cosci-focus-composer', focusComposer);
    return () => {
      window.removeEventListener('cosci-new-chat', resetWorkspace);
      window.removeEventListener('cosci-focus-composer', focusComposer);
    };
  }, [focusComposer, resetWorkspace]);

  // Handles the same two actions when they arrive as router navigation state
  // instead (see ChatWorkspaceLocationState), then clears the state so it
  // doesn't re-fire on a later re-render or back/forward navigation.
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

  // Publishes the current draft goal (or started session title) as the app
  // shell's header title via a custom event, since the header lives outside
  // this component's subtree. Clears it back to empty on cleanup/unmount.
  useEffect(() => {
    const title = draftSpec
      ? conciseTitle(draftSpec.goal)
      : startedSession
        ? startedSession.title
        : '';
    window.dispatchEvent(
      new CustomEvent('cosci-header-title', {detail: title}),
    );
    return () => {
      window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
    };
  }, [draftSpec, startedSession]);

  // Merge every timeline-worthy piece of session state (messages, draft spec,
  // confirmed spec, started session) into one list of TimelineItems, each
  // carrying the rendered card/bubble node plus enough metadata to sort them.
  const timelineItems: TimelineItem[] = [];
  // Each chat message becomes a ChatBubble; `order` preserves message array
  // order as a tiebreaker when timestamps collide.
  for (const [index, message] of messages.entries()) {
    timelineItems.push({
      id: `local-message-${message.id}`,
      at: message.created_at,
      order: index,
      node: (
        <ChatBubble
          message={message}
          onEdit={() => handleEditMessage(message)}
          onCopyRequest={() => void handleCopyRequest(message)}
          onRetry={() => handleRetryMessage(message)}
        />
      ),
    });
  }
  // Editable draft run spec awaiting confirmation: focus/tier edits write
  // straight back into draftSpec, and cancel/edit/retry/start delegate to the
  // session hook's handlers.
  if (draftSpec && draftSpecCreatedAt !== null) {
    timelineItems.push({
      id: 'draft-spec',
      at: draftSpecCreatedAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={draftSpec}
          isStarting={isStarting}
          onFocusChange={focus =>
            setDraftSpec(current => (current ? {...current, focus} : current))
          }
          onTierChange={tier =>
            setDraftSpec(current => (current ? {...current, tier} : current))
          }
          onCancel={handleCancelDraftSpec}
          onEdit={() => handleEditPlan(draftSpec)}
          onRetry={() => handleRetryDraftSpec()}
          onStart={() => void handleStartRun()}
        />
      ),
    });
  }
  // Read-only confirmed spec once the plan has been locked in (e.g. after an
  // edit round-trip): all mutation handlers are no-ops and `locked` disables
  // the option cards; retrying re-stages it as an editable draft again.
  if (confirmedSpec && confirmedSpecCreatedAt !== null) {
    timelineItems.push({
      id: 'confirmed-spec',
      at: confirmedSpecCreatedAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={confirmedSpec}
          isStarting={false}
          locked
          onFocusChange={() => undefined}
          onTierChange={() => undefined}
          onCancel={() => undefined}
          onEdit={() => handleEditPlan(confirmedSpec)}
          onRetry={() => {
            stageDraftSpec(confirmedSpec);
          }}
          onStart={() => undefined}
        />
      ),
    });
  }
  // Terminal timeline entry once the backend run has actually started;
  // opening it navigates to the run detail page, "retry" just bumps its
  // timestamp so it re-sorts to the current time.
  if (startedSession) {
    timelineItems.push({
      id: `started-session-${startedSession.id}`,
      at: startedSession.at,
      order: 60,
      node: (
        <StartedSessionCard
          session={startedSession}
          onOpen={() => void navigate(`/runs/${startedSession.id}/details`)}
          onRetry={() =>
            setStartedSession(current =>
              current ? {...current, at: Date.now() / 1000} : current,
            )
          }
          onNewTopic={() => {
            resetWorkspace();
            focusComposer();
          }}
        />
      ),
    });
  }
  // Chronological order, with `order` breaking ties between items created in
  // the same tick (e.g. a message and a spec card stamped at the same time).
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  // Cheap fingerprint of the timeline's identity/order used below to decide
  // whether an auto-scroll is warranted, without deep-comparing React nodes.
  const timelineSignature = timelineItems
    .map(item => `${item.id}:${item.at}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  // Once a run has started, always anchor to the bottom. Otherwise, a newly
  // arrived spec card (which is tall) anchors to the top so its heading is
  // visible; anything else (chat bubbles) anchors to the bottom as usual.
  const timelineAnchorMode = startedSession
    ? 'bottom'
    : latestTimelineItemId === 'draft-spec' ||
        latestTimelineItemId === 'confirmed-spec'
      ? 'top'
      : 'bottom';

  // Auto-scrolls the timeline whenever its signature changes (new item, or an
  // item's timestamp changed), skipping the very first render's signature and
  // any re-render that doesn't actually change the timeline. The zero-delay
  // timeout defers until after layout so scrollHeight reflects the new DOM.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || previousTimelineSignature.current === timelineSignature) {
      return;
    }
    previousTimelineSignature.current = timelineSignature;
    const timeout = window.setTimeout(() => {
      scroller.scrollTop =
        timelineAnchorMode === 'top' ? 0 : scroller.scrollHeight;
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [timelineAnchorMode, timelineSignature]);

  // Belt-and-suspenders scroll-to-bottom specifically when a session starts,
  // independent of the signature-based effect above, since the started-card
  // arriving can coincide with other timeline changes.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!startedSession || !scroller) {
      return;
    }
    const timeout = window.setTimeout(() => {
      scroller.scrollTop = scroller.scrollHeight;
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [startedSession]);

  // The composer overlays the timeline, so reserve exactly its height as the
  // timeline's bottom padding — otherwise the last item is trapped under the
  // composer (padding too small) or floats above it (too large). Tracks the
  // composer as it auto-grows.
  useEffect(() => {
    const composer = composerRef.current;
    const scroller = scrollRef.current;
    if (!hasConversation || !composer || !scroller) return;
    const sync = () => {
      scroller.style.setProperty(
        '--chat-composer-h',
        `${composer.offsetHeight}px`,
      );
    };
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(composer);
    return () => observer.disconnect();
  }, [hasConversation]);

  return (
    <div className={HOME_WORKSPACE_CLASSES}>
      <main className={HOME_WORKSPACE_MAIN_CLASSES}>
        {/* Before any conversation exists, show the session-home stage
            (greeting, suggestions, recents); once one starts, switch to the
            scrolling timeline + overlaid composer below. */}
        {!hasConversation ? (
          <HomeStage
            input={input}
            setInput={setInput}
            pubmedEnabled={pubmedEnabled}
            onPubmedEnabledChange={setPubmedEnabled}
            onSubmit={handleSubmit}
            runs={history}
            scoresByRunId={homeScores}
            showAllRecents={showAllRecents}
            onToggleShowAll={() => setShowAllRecents(current => !current)}
          />
        ) : (
          <>
            <section ref={scrollRef} className={CHAT_TIMELINE_CLASSES}>
              <div className={CHAT_COLUMN_CLASSES}>
                {timelineItems.map(item => (
                  <Fragment key={item.id}>{item.node}</Fragment>
                ))}

                {/* Session-level error (e.g. a failed submit/start), shown
                    below the last timeline item. */}
                {error && (
                  <div
                    role="alert"
                    className="rounded-md border p-3 text-sm"
                    style={{
                      borderColor: 'var(--md-sys-color-error)',
                      color: 'var(--md-sys-color-error)',
                    }}
                  >
                    {error}
                  </div>
                )}
              </div>
            </section>
            {/* Overlaid, non-scrolling composer; setupDraftMode swaps its
                placeholder copy while a draft/confirmed spec or started
                session is in view, and disabled locks input while starting. */}
            <div ref={composerRef} className={CHAT_COMPOSER_CLASSES}>
              <div className={CHAT_COLUMN_CLASSES}>
                <Composer
                  input={input}
                  setInput={setInput}
                  setupDraftMode={Boolean(draftSpec || startedSession)}
                  disabled={isStarting}
                  pubmedEnabled={pubmedEnabled}
                  onPubmedEnabledChange={setPubmedEnabled}
                  onSubmit={handleSubmit}
                />
              </div>
            </div>
          </>
        )}
        {/* Toast is portaled to <body> so no ancestor stacking context can
            trap it; see HOME_TOAST_CLASSES for the fixed-position styling. */}
        {toast &&
          createPortal(
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
          )}
      </main>
    </div>
  );
}

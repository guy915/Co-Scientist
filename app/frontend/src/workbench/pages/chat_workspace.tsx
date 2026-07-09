import {
  Fragment,
  type Dispatch,
  type ReactNode,
  type RefObject,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {createPortal} from 'react-dom';
import {
  type NavigateFunction,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import {type RunFocus, type RunTier} from '@/api/runs';
import {conciseTitle} from '@/lib/text';
import {useToast, type ToastState} from '../hooks/use_toast';
import {useRunHistory} from '../hooks/use_run_history';
import {useChatSession} from '../hooks/use_chat_session';
import {type InferredRunSpec} from '../run_spec';
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
  type ChatEntry,
  ChatBubble,
  RunSpecCard,
  type StartedSession,
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
  // (draftSpec/startedSession/hasConversation) are destructured for brevity.
  const session = useChatSession({
    reloadHistory,
    focusComposer,
    setToast,
    pubmedEnabled,
  });
  const {draftSpec, startedSession, hasConversation} = session;

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
    () => syncHeaderTitle(draftSpec, startedSession),
    [draftSpec, startedSession],
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
            setupDraftMode={Boolean(draftSpec || startedSession)}
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
  draftSpec: InferredRunSpec | null,
  startedSession: StartedSession | null,
) {
  const title = draftSpec
    ? conciseTitle(draftSpec.goal)
    : startedSession
      ? startedSession.title
      : '';
  window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: title}));
  return () => {
    window.dispatchEvent(new CustomEvent('cosci-header-title', {detail: ''}));
  };
}

// Effect body for the composer-resize sync above: while there's an active
// conversation, mirrors the composer's measured height into the timeline's
// `--chat-composer-h` custom property so its bottom padding tracks the
// composer as it auto-grows.
function syncComposerHeight(
  composerRef: RefObject<HTMLDivElement | null>,
  scrollRef: RefObject<HTMLDivElement | null>,
  hasConversation: boolean,
) {
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
}

// Builds the in-conversation timeline and owns the two refs that keep it
// laid out correctly: the auto-scroll ref (see useChatTimelineScroll) and
// the composer ref whose measured height feeds the timeline's bottom padding
// (see syncComposerHeight). Grouped together since all three only matter
// once there's a conversation to lay out, and the composer-height sync
// depends on the scroll ref the timeline hook returns.
function useConversationLayout(
  session: ReturnType<typeof useChatSession>,
  navigate: NavigateFunction,
  resetWorkspace: () => void,
  focusComposer: () => void,
) {
  // Wraps the overlaid composer; its measured height drives the timeline's
  // bottom padding (see the ResizeObserver effect below).
  const composerRef = useRef<HTMLDivElement>(null);

  // Merges messages/draft/confirmed/started state into one sorted timeline;
  // `session` supplies every field but navigate/resetWorkspace/focusComposer.
  const timelineItems = buildTimelineItems({
    ...session,
    navigate,
    resetWorkspace,
    focusComposer,
  });

  // Auto-scrolls the timeline as it changes shape/order (see the hook).
  const scrollRef = useChatTimelineScroll(
    timelineItems,
    session.startedSession,
  );

  // The composer overlays the timeline, so its measured height becomes the
  // timeline's bottom padding; tracks the composer as it auto-grows.
  useEffect(
    () => syncComposerHeight(composerRef, scrollRef, session.hasConversation),
    [session.hasConversation, scrollRef],
  );

  return {timelineItems, scrollRef, composerRef};
}

// The in-conversation view: the scrolling timeline (rendered items plus any
// session-level error) and the composer overlaid at the bottom. Split out of
// ChatWorkspace as a pure render component; every ref/handler it needs is
// owned by ChatWorkspace and passed in as a prop. Not exported, so it takes
// the whole `session` object rather than re-declaring each field it reads.
function ConversationView({
  scrollRef,
  timelineItems,
  composerRef,
  session,
  setupDraftMode,
  pubmedEnabled,
  onPubmedEnabledChange,
}: {
  scrollRef: RefObject<HTMLDivElement | null>;
  timelineItems: TimelineItem[];
  composerRef: RefObject<HTMLDivElement | null>;
  session: Pick<
    ReturnType<typeof useChatSession>,
    'input' | 'setInput' | 'error' | 'isStarting' | 'handleSubmit'
  >;
  setupDraftMode: boolean;
  pubmedEnabled: boolean;
  onPubmedEnabledChange: (value: boolean) => void;
}) {
  return (
    <>
      <TimelineSection
        scrollRef={scrollRef}
        timelineItems={timelineItems}
        error={session.error}
      />
      <ComposerSection
        composerRef={composerRef}
        session={session}
        setupDraftMode={setupDraftMode}
        pubmedEnabled={pubmedEnabled}
        onPubmedEnabledChange={onPubmedEnabledChange}
      />
    </>
  );
}

// The scrolling timeline: every rendered item in order, plus any
// session-level error (e.g. a failed submit/start) shown below the last one.
function TimelineSection({
  scrollRef,
  timelineItems,
  error,
}: {
  scrollRef: RefObject<HTMLDivElement | null>;
  timelineItems: TimelineItem[];
  error: string | null;
}) {
  return (
    <section ref={scrollRef} className={CHAT_TIMELINE_CLASSES}>
      <div className={CHAT_COLUMN_CLASSES}>
        {timelineItems.map(item => (
          <Fragment key={item.id}>{item.node}</Fragment>
        ))}
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
  );
}

// Overlaid, non-scrolling composer; setupDraftMode swaps its placeholder
// copy while a draft/confirmed spec or started session is in view, and
// disabled locks input while starting.
function ComposerSection({
  composerRef,
  session,
  setupDraftMode,
  pubmedEnabled,
  onPubmedEnabledChange,
}: {
  composerRef: RefObject<HTMLDivElement | null>;
  session: Pick<
    ReturnType<typeof useChatSession>,
    'input' | 'setInput' | 'isStarting' | 'handleSubmit'
  >;
  setupDraftMode: boolean;
  pubmedEnabled: boolean;
  onPubmedEnabledChange: (value: boolean) => void;
}) {
  const {input, setInput, isStarting, handleSubmit} = session;
  return (
    <div ref={composerRef} className={CHAT_COMPOSER_CLASSES}>
      <div className={CHAT_COLUMN_CLASSES}>
        <Composer
          input={input}
          setInput={setInput}
          setupDraftMode={setupDraftMode}
          disabled={isStarting}
          pubmedEnabled={pubmedEnabled}
          onPubmedEnabledChange={onPubmedEnabledChange}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
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

// Dependencies buildTimelineItems (and the per-category helpers below) need
// to render each kind of timeline entry; see ChatWorkspace's `session` plus
// its own navigate/resetWorkspace/focusComposer for where these come from.
interface BuildTimelineItemsArgs {
  messages: ChatEntry[];
  handleEditMessage: (message: ChatEntry) => void;
  handleCopyRequest: (message: ChatEntry) => Promise<void>;
  handleRetryMessage: (message: ChatEntry) => void;
  draftSpec: InferredRunSpec | null;
  draftSpecCreatedAt: number | null;
  setDraftSpec: Dispatch<SetStateAction<InferredRunSpec | null>>;
  isStarting: boolean;
  handleCancelDraftSpec: () => void;
  handleEditPlan: (spec: InferredRunSpec) => void;
  handleRetryDraftSpec: () => void;
  handleStartRun: () => Promise<void>;
  confirmedSpec: InferredRunSpec | null;
  confirmedSpecCreatedAt: number | null;
  stageDraftSpec: (spec: InferredRunSpec, createdAt?: number) => void;
  startedSession: StartedSession | null;
  setStartedSession: Dispatch<SetStateAction<StartedSession | null>>;
  navigate: NavigateFunction;
  resetWorkspace: () => void;
  focusComposer: () => void;
}

// Each chat message becomes a ChatBubble; `order` preserves message array
// order as a tiebreaker when timestamps collide.
function messageTimelineItems({
  messages,
  handleEditMessage,
  handleCopyRequest,
  handleRetryMessage,
}: Pick<
  BuildTimelineItemsArgs,
  'messages' | 'handleEditMessage' | 'handleCopyRequest' | 'handleRetryMessage'
>): TimelineItem[] {
  return messages.map((message, index) => ({
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
  }));
}

// Editable draft run spec awaiting confirmation: focus/tier edits write
// straight back into draftSpec, and cancel/edit/retry/start delegate to the
// session hook's handlers.
function draftTimelineItems({
  draftSpec,
  draftSpecCreatedAt,
  isStarting,
  setDraftSpec,
  handleCancelDraftSpec,
  handleEditPlan,
  handleRetryDraftSpec,
  handleStartRun,
}: Pick<
  BuildTimelineItemsArgs,
  | 'draftSpec'
  | 'draftSpecCreatedAt'
  | 'isStarting'
  | 'setDraftSpec'
  | 'handleCancelDraftSpec'
  | 'handleEditPlan'
  | 'handleRetryDraftSpec'
  | 'handleStartRun'
>): TimelineItem[] {
  if (!draftSpec || draftSpecCreatedAt === null) return [];
  return [
    {
      id: 'draft-spec',
      at: draftSpecCreatedAt,
      order: 50,
      node: (
        <RunSpecCard
          spec={draftSpec}
          isStarting={isStarting}
          onFocusChange={(focus: RunFocus) =>
            setDraftSpec(current => (current ? {...current, focus} : current))
          }
          onTierChange={(tier: RunTier) =>
            setDraftSpec(current => (current ? {...current, tier} : current))
          }
          onCancel={handleCancelDraftSpec}
          onEdit={() => handleEditPlan(draftSpec)}
          onRetry={() => handleRetryDraftSpec()}
          onStart={() => void handleStartRun()}
        />
      ),
    },
  ];
}

// Read-only confirmed spec once the plan has been locked in (e.g. after an
// edit round-trip): all mutation handlers are no-ops and `locked` disables
// the option cards; retrying re-stages it as an editable draft again.
function confirmedSpecTimelineItems({
  confirmedSpec,
  confirmedSpecCreatedAt,
  handleEditPlan,
  stageDraftSpec,
}: Pick<
  BuildTimelineItemsArgs,
  | 'confirmedSpec'
  | 'confirmedSpecCreatedAt'
  | 'handleEditPlan'
  | 'stageDraftSpec'
>): TimelineItem[] {
  if (!confirmedSpec || confirmedSpecCreatedAt === null) return [];
  return [
    {
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
    },
  ];
}

// Terminal timeline entry once the backend run has actually started; opening
// it navigates to the run detail page, "retry" just bumps its timestamp so
// it re-sorts to the current time.
function startedTimelineItems({
  startedSession,
  setStartedSession,
  navigate,
  resetWorkspace,
  focusComposer,
}: Pick<
  BuildTimelineItemsArgs,
  | 'startedSession'
  | 'setStartedSession'
  | 'navigate'
  | 'resetWorkspace'
  | 'focusComposer'
>): TimelineItem[] {
  if (!startedSession) return [];
  return [
    {
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
    },
  ];
}

// Merges every timeline-worthy piece of session state (messages, draft spec,
// confirmed spec, started session) into one list of TimelineItems, each
// carrying the rendered card/bubble node plus enough metadata to sort them,
// and returns them in chronological order.
function buildTimelineItems(args: BuildTimelineItemsArgs): TimelineItem[] {
  const timelineItems: TimelineItem[] = [
    ...messageTimelineItems(args),
    ...draftTimelineItems(args),
    ...confirmedSpecTimelineItems(args),
    ...startedTimelineItems(args),
  ];
  // Chronological order, with `order` breaking ties between items created in
  // the same tick (e.g. a message and a spec card stamped at the same time).
  timelineItems.sort((a, b) => a.at - b.at || a.order - b.order);
  return timelineItems;
}

// Cheap fingerprint of the timeline's identity/order, used to detect when it
// actually changed shape/order without deep-comparing React nodes, plus
// whether an auto-scroll should anchor to the top (a newly arrived, tall
// spec card) or bottom (everything else, and always once a session has
// started).
function timelineScrollTarget(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
): {signature: string; anchorMode: 'top' | 'bottom'} {
  const signature = timelineItems
    .map(item => `${item.id}:${item.at}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  // Once a run has started, always anchor to the bottom. Otherwise, a newly
  // arrived spec card (which is tall) anchors to the top so its heading is
  // visible; anything else (chat bubbles) anchors to the bottom as usual.
  const anchorMode: 'top' | 'bottom' = startedSession
    ? 'bottom'
    : latestTimelineItemId === 'draft-spec' ||
        latestTimelineItemId === 'confirmed-spec'
      ? 'top'
      : 'bottom';
  return {signature, anchorMode};
}

// Effect body for the signature-based auto-scroll below: fires whenever the
// timeline's signature changes (new item, or an item's timestamp changed),
// skipping the very first render's signature and any re-render that doesn't
// actually change the timeline. The zero-delay timeout defers until after
// layout so scrollHeight reflects the new DOM.
function syncTimelineScroll(
  scrollRef: RefObject<HTMLDivElement | null>,
  previousTimelineSignature: RefObject<string>,
  timelineSignature: string,
  timelineAnchorMode: 'top' | 'bottom',
) {
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
}

// Effect body for the belt-and-suspenders scroll-to-bottom below: fires
// specifically when a session starts, independent of the signature-based
// effect above, since the started-card arriving can coincide with other
// timeline changes.
function syncStartedSessionScroll(
  scrollRef: RefObject<HTMLDivElement | null>,
  startedSession: StartedSession | null,
) {
  const scroller = scrollRef.current;
  if (!startedSession || !scroller) {
    return;
  }
  const timeout = window.setTimeout(() => {
    scroller.scrollTop = scroller.scrollHeight;
  }, 0);
  return () => window.clearTimeout(timeout);
}

/**
 * Owns the timeline's auto-scroll behavior: derives a scroll signature and
 * anchor mode from the current items (see timelineScrollTarget), then scrolls
 * the returned ref accordingly whenever the timeline changes or a session
 * starts (see syncTimelineScroll and syncStartedSessionScroll).
 *
 * @param timelineItems The current, already-sorted timeline items.
 * @param startedSession The started session, if any (always anchors bottom).
 * @returns The ref to attach to the scrollable timeline container.
 */
function useChatTimelineScroll(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
) {
  // Scrollable timeline container; scrollTop is driven imperatively below.
  const scrollRef = useRef<HTMLDivElement>(null);
  // Last timeline signature we auto-scrolled for, so the effect below only
  // fires when the timeline actually changed shape/order.
  const previousTimelineSignature = useRef('');

  const {signature: timelineSignature, anchorMode: timelineAnchorMode} =
    timelineScrollTarget(timelineItems, startedSession);

  useEffect(
    () =>
      syncTimelineScroll(
        scrollRef,
        previousTimelineSignature,
        timelineSignature,
        timelineAnchorMode,
      ),
    [timelineAnchorMode, timelineSignature],
  );

  useEffect(
    () => syncStartedSessionScroll(scrollRef, startedSession),
    [startedSession],
  );

  return scrollRef;
}

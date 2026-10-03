import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useState,
  Fragment,
  type RefObject,
  useRef,
} from 'react';
import {createPortal} from 'react-dom';
import {
  useLocation,
  useNavigate,
  useParams,
  type NavigateFunction,
} from 'react-router-dom';
import {conciseTitle} from '@/lib/text';
import {HEADER_TITLE_EVENT, NEW_CHAT_EVENT} from '../dom_events';
import {useToast, type ToastState} from '../hooks/timers';
import {useRunHistoryContext} from '../hooks/history_context';
import {
  useChatSession,
  type SpecStage,
  type LinkedDraftRecovery,
} from '../hooks/use_chat_session';
import {useChatRehydration} from '../hooks/use_chat_rehydrate';
import {type ConnectorToggleProps, Composer} from './chat_composer';
import {HomeStage} from './chat_home_stage';
import type {StartedSession} from './chat_timeline_run_spec_card';
import {pendingQuestions} from './chat_questions';
import {QuestionChooser} from './chat_questions';
import {
  buildTimelineItems,
  type TimelineItem,
  DRAFT_SPEC_ITEM_ID,
} from './chat_workspace_timeline';
import {TIMELINE_ANCHOR_ATTRIBUTE} from './chat_timeline_bubble';

// The landing page under the home stage, split into its own chunk so the
// chat home's first paint does not wait on it.
const HomeLanding = lazy(() => import('./home_landing'));

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

const CHAT_COLUMN_CLASSES =
  'reference-chat-column mx-auto grid w-[min(100%,50.75rem)] gap-[1.15rem]';

// Effect body for the composer-resize sync below: while there's an active
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

/**
 * Builds the in-conversation timeline and owns the two refs that keep it laid
 * out correctly: the auto-scroll ref (see useChatTimelineScroll) and the
 * composer ref whose measured height feeds the timeline's bottom padding (see
 * syncComposerHeight).
 *
 * Grouped together since all three only matter once there's a conversation to
 * lay out, and the composer-height sync depends on the scroll ref the timeline
 * hook returns.
 *
 * @param session The chat session state machine.
 * @param navigate Router navigation function for the started-session card.
 * @param resetWorkspace Clears the session back to the empty home stage.
 * @param focusComposer Focuses the composer textarea on the next frame.
 * @returns The sorted timeline items plus the scroll and composer refs.
 */
export function useConversationLayout(
  session: ReturnType<typeof useChatSession>,
  navigate: NavigateFunction,
  resetWorkspace: () => void,
  focusComposer: () => void,
  linkedDraftRecovery: LinkedDraftRecovery,
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
    linkedDraftRecovery,
  });

  // Auto-scrolls the timeline as it changes shape/order (see the hook).
  const scrollRef = useChatTimelineScroll(
    timelineItems,
    session.startedSession,
    session.isAwaitingAgent,
    session.interview?.id,
  );

  // The composer overlays the timeline, so its measured height becomes the
  // timeline's bottom padding; tracks the composer as it auto-grows.
  useEffect(
    () => syncComposerHeight(composerRef, scrollRef, session.hasConversation),
    [session.hasConversation, scrollRef],
  );

  return {timelineItems, scrollRef, composerRef};
}

// Props for ConversationView, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
export interface ConversationViewProps {
  scrollRef: RefObject<HTMLDivElement | null>;
  timelineItems: TimelineItem[];
  composerRef: RefObject<HTMLDivElement | null>;
  session: Pick<
    ReturnType<typeof useChatSession>,
    | 'input'
    | 'setInput'
    | 'error'
    | 'isStarting'
    | 'isAwaitingAgent'
    | 'startedSession'
    | 'handleSubmit'
    | 'handleStop'
    | 'interview'
    | 'handleAnswerQuestions'
  >;
  setupDraftMode: boolean;
  connectors: ConnectorToggleProps;
}

/**
 * The in-conversation view: the scrolling timeline (rendered items plus any
 * session-level error) and the composer overlaid at the bottom.
 *
 * Split out of ChatWorkspace as a pure render component; every ref/handler it
 * needs is owned by ChatWorkspace and passed in as a prop. It takes the whole
 * `session` object rather than re-declaring each field it reads.
 */
export function ConversationView(props: ConversationViewProps) {
  return (
    <>
      <TimelineSection
        scrollRef={props.scrollRef}
        timelineItems={props.timelineItems}
        error={props.session.error}
      />
      <ComposerSection
        composerRef={props.composerRef}
        session={props.session}
        setupDraftMode={props.setupDraftMode}
        connectors={props.connectors}
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
    <section
      ref={scrollRef}
      className="reference-chat-timeline flex-1 overflow-y-auto px-4 pt-5"
    >
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

// Props for ComposerSection, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
interface ComposerSectionProps {
  composerRef: RefObject<HTMLDivElement | null>;
  session: Pick<
    ReturnType<typeof useChatSession>,
    | 'input'
    | 'setInput'
    | 'isStarting'
    | 'isAwaitingAgent'
    | 'startedSession'
    | 'handleSubmit'
    | 'handleStop'
    | 'interview'
    | 'handleAnswerQuestions'
  >;
  setupDraftMode: boolean;
  connectors: ConnectorToggleProps;
}

// The placeholder shown once a run has started: the composer stays live
// from here on, but it now asks the run rather than continuing the closed
// interview -- deliberately distinct from the "edit session details"
// setupDraftMode wording and from Composer's own disabled-state copy,
// neither of which describes this state.
const ASK_RUN_PLACEHOLDER = 'Ask a question about this research session';

// Overlaid, non-scrolling composer; setupDraftMode swaps its placeholder
// copy while a draft/confirmed spec is in view, busy blocks submits while
// starting. A started session used to lock the composer outright once its
// interview closed server-side (A17: it kept posting turns to a completed
// interview). It no longer does -- handleSubmit itself routes a started
// session's submit to the run's Q&A endpoint instead (see
// chat_session_handlers.ts's buildChatHandlers), so the composer only swaps
// its placeholder here. The send button becomes Stop while either an
// interview turn or a run Q&A turn (not the run start round trip, which
// isStarting alone also covers) is in flight.
function ComposerSection(props: ComposerSectionProps) {
  const {
    input,
    setInput,
    isStarting,
    isAwaitingAgent,
    startedSession,
    handleSubmit,
    handleStop,
  } = props.session;
  return (
    <div ref={props.composerRef} className="reference-chat-composer px-4 pb-8">
      <div className={CHAT_COLUMN_CLASSES}>
        <Composer
          input={input}
          setInput={setInput}
          setupDraftMode={props.setupDraftMode}
          busy={isStarting}
          placeholderOverride={startedSession ? ASK_RUN_PLACEHOLDER : undefined}
          autoFocus
          connectors={props.connectors}
          onSubmit={handleSubmit}
          stoppable={isAwaitingAgent}
          onStop={handleStop}
          aboveInput={composerQuestions(props)}
        />
      </div>
    </div>
  );
}

/**
 * The chooser for the question the Agent is waiting on, or nothing.
 *
 * Rendered into the composer's own shell (Composer's `aboveInput`), so it
 * grows out of the top of the input box and the ResizeObserver above keeps
 * the timeline's bottom padding clear of it without knowing it exists.
 *
 * Withheld while a turn is in flight: the answer has already been sent, and
 * the questions it answered are about to be replaced by the next turn's.
 * Keyed by the turn that asked, so a new turn's chooser starts fresh rather
 * than inheriting the last one's selections or its dismissal.
 */
function composerQuestions(props: ComposerSectionProps) {
  const pending = pendingQuestions(props.session.interview);
  if (!pending || props.session.isAwaitingAgent) return null;
  return (
    <QuestionChooser
      key={pending.turnId}
      questions={pending.questions}
      onAnswer={props.session.handleAnswerQuestions}
    />
  );
}

// Cheap fingerprint of the timeline's identity/order, used to detect when it
// actually changed shape/order without deep-comparing React nodes, plus
// whether an auto-scroll should bring the newly arrived plan turn's own top
// edge into view or simply follow the bottom (everything else, and always
// once a session has started).
//
// Only the *draft* plan card anchors that way, and only while no run has
// started. The confirmed card deliberately does not: it replaces the draft
// in place, so it is the same card the reader is already looking at rather
// than a new arrival -- and it becomes the timeline's last item for the
// length of the create+start round trip, which is exactly when the reader is
// waiting for the reply that follows it.
function timelineScrollTarget(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
): {signature: string; anchorMode: 'plan' | 'bottom'} {
  const signature = timelineItems
    .map(item => `${item.id}:${item.at}:${item.revision ?? ''}`)
    .join('|');
  const latestTimelineItemId =
    timelineItems.length > 0 ? timelineItems[timelineItems.length - 1].id : '';
  const anchorMode: 'plan' | 'bottom' =
    !startedSession && latestTimelineItemId === DRAFT_SPEC_ITEM_ID
      ? 'plan'
      : 'bottom';
  return {signature, anchorMode};
}

// How close to the bottom still counts as following along. Anything further
// up is a reader who scrolled there deliberately, and that position is
// theirs to keep: a streaming turn appends text on every token, so without
// this the timeline hauled them back down several times a second and reading
// back over the reply was impossible until the turn finished.
const FOLLOW_THRESHOLD_PX = 64;

// The refs the scroll effects below share: the scroller itself, the last
// signature auto-scrolled for, the one-shot "still needs its initial bottom
// scroll" flag (see armInitialScroll and shouldForceInitialBottom), and the
// scrollTop this hook itself last left the scroller at (see isPinnedToBottom).
interface TimelineScrollRefs {
  scroller: RefObject<HTMLDivElement | null>;
  previousSignature: RefObject<string>;
  needsInitialScroll: RefObject<boolean>;
  lastAppliedTop: RefObject<number>;
}

// A scrollTop no element can hold, for "this hook has not scrolled yet".
const NO_APPLIED_TOP = -1;

/**
 * Whether the reader is close enough to the bottom to be following along.
 *
 * Measured here, at the moment of the scroll, rather than tracked from a
 * `scroll` listener. The listener version has a hole: the browser delivers
 * scroll events asynchronously, so a token landing in the same frame as the
 * reader's gesture still sees the stale "at the bottom" flag and hauls them
 * back down -- and once back at the bottom the flag is true again, so they
 * are stuck there. Only ever asked about a reader who has actually moved
 * (see isPinnedToBottom), since the gap it measures includes the growth
 * that prompted this update.
 */
function isFollowingBottom(scroller: HTMLDivElement): boolean {
  const gap =
    scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  return gap <= FOLLOW_THRESHOLD_PX;
}

/**
 * Whether the timeline should still follow the bottom for this update.
 *
 * The gap alone cannot answer this. It is measured *after* the DOM has
 * grown, and a fragment that adds more than FOLLOW_THRESHOLD_PX in one
 * commit -- a finished markdown block, a table, a few lines at once --
 * therefore reads exactly like a reader who scrolled away. That reading
 * latches: skipping leaves scrollTop where it was, so every later fragment
 * measures an even larger gap and the turn stops following for good a
 * second or two in. Growth is not a gesture, so it must not be read as one.
 *
 * A gesture is the only thing that moves scrollTop without this hook doing
 * it -- content growing at the bottom leaves scrollTop untouched. So an
 * unchanged scrollTop since our own last scroll means the reader has not
 * moved, whatever the gap now says, and the timeline stays pinned. Once
 * they do move, the gap decides: still near the bottom keeps following,
 * further up hands the position to them until they come back down.
 */
function isPinnedToBottom(
  refs: TimelineScrollRefs,
  scroller: HTMLDivElement,
): boolean {
  if (scroller.scrollTop === refs.lastAppliedTop.current) return true;
  return isFollowingBottom(scroller);
}

// Drives the scroller to the bottom and records where that left it, so the
// next update can tell this hook's own scroll from a reader's gesture (see
// isPinnedToBottom). Reads scrollTop back rather than assuming the assigned
// value: the browser clamps it to the content's own end.
function scrollToBottom(
  refs: TimelineScrollRefs,
  scroller: HTMLDivElement,
): void {
  scroller.scrollTop = scroller.scrollHeight;
  refs.lastAppliedTop.current = scroller.scrollTop;
}

// Breathing room left above an anchored turn, matching the timeline's own
// top padding (CHAT_TIMELINE_CLASSES' `pt-5`) so the turn sits where the
// first turn of a fresh conversation sits rather than flush against the
// pane's edge.
const ANCHOR_TOP_INSET_PX = 20;

/**
 * Scrolls the timeline so the given item's own top edge sits just below the
 * scroller's top edge.
 *
 * The plan turn is tall, so following the bottom would open it at its Start
 * button with the message that introduces it off screen. What it must never
 * do is scroll the *container* to zero: that is the top of the whole
 * conversation, which for anything past a couple of turns threw the reader
 * back to their opening message the moment the plan arrived.
 *
 * Falls back to the bottom when the element cannot be found, for the same
 * reason -- zero is never the answer here.
 */
function scrollItemToTop(
  refs: TimelineScrollRefs,
  scroller: HTMLDivElement,
  itemId: string,
): void {
  const anchor = scroller.querySelector<HTMLElement>(
    `[${TIMELINE_ANCHOR_ATTRIBUTE}="${itemId}"]`,
  );
  if (!anchor) {
    scrollToBottom(refs, scroller);
    return;
  }
  // The element's on-screen offset from the scroller's own top edge is how
  // far the scroller has to travel to put it there (mirrors
  // lib/smooth_scroll.ts). Assignment clamps, so an anchor near the end of a
  // short timeline simply lands as low as the content allows.
  const offset =
    anchor.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  scroller.scrollTop += offset - ANCHOR_TOP_INSET_PX;
  // Deliberately not recorded as an applied scroll: this placement leaves
  // the reader well above the bottom on purpose, so remembering it would
  // make "hasn't moved since" read as "following the bottom" (see
  // isPinnedToBottom) and send them to the card's Start button the moment
  // confirming it swapped the card back to bottom anchoring -- the second
  // jump this anchoring exists to prevent. Only a bottom scroll is a pin.
  refs.lastAppliedTop.current = NO_APPLIED_TOP;
}

// Whether this signature change is the one-shot initial landing: the first
// *non-empty* signature since needsInitialScroll was last armed (a mount, or
// a conversation switch -- see armInitialScroll). It wins over both the
// follow-threshold guard and the plan anchor, because neither is meant for
// this moment: the guard exists to protect a reader who is already reading,
// which nobody is yet, and the plan anchor exists for a plan card *arriving*
// mid-conversation, not for a reopened chat that happens to end on one.
// Consumes the flag on a true first-non-empty firing so later signatures
// (including a later empty-then-non-empty blip) go through the guard as
// usual.
function shouldForceInitialBottom(
  refs: TimelineScrollRefs,
  timelineSignature: string,
): boolean {
  if (timelineSignature === '' || !refs.needsInitialScroll.current) {
    return false;
  }
  refs.needsInitialScroll.current = false;
  return true;
}

// Whether a bottom-anchored update should be skipped outright: not the
// initial landing (which always wins, see shouldForceInitialBottom), anchored
// to the bottom, and the reader has scrolled away from it -- the case
// FOLLOW_THRESHOLD_PX exists to protect.
function shouldSkipFollow(
  refs: TimelineScrollRefs,
  forceInitialBottom: boolean,
  timelineAnchorMode: 'plan' | 'bottom',
  scroller: HTMLDivElement,
): boolean {
  return (
    !forceInitialBottom &&
    timelineAnchorMode === 'bottom' &&
    !isPinnedToBottom(refs, scroller)
  );
}

// Performs the deferred scroll once layout has settled. The initial landing
// and every ordinary bottom-anchored update jump to the very bottom; only a
// plan card *arriving* mid-conversation (not the initial landing, even when
// it happens to end on one -- see shouldForceInitialBottom) opens at its own
// top instead.
function applyTimelineScroll(
  refs: TimelineScrollRefs,
  scroller: HTMLDivElement,
  forceInitialBottom: boolean,
  timelineAnchorMode: 'plan' | 'bottom',
) {
  if (!forceInitialBottom && timelineAnchorMode === 'plan') {
    scrollItemToTop(refs, scroller, DRAFT_SPEC_ITEM_ID);
    return;
  }
  scrollToBottom(refs, scroller);
}

// Effect body for the signature-based auto-scroll below: fires whenever the
// timeline's signature changes (new item, or an item's timestamp changed),
// skipping the very first render's signature and any re-render that doesn't
// actually change the timeline. The zero-delay timeout defers until after
// layout, so both scrollHeight and the anchor's rect reflect the new DOM.
function syncTimelineScroll(
  refs: TimelineScrollRefs,
  timelineSignature: string,
  timelineAnchorMode: 'plan' | 'bottom',
) {
  const scroller = refs.scroller.current;
  if (!scroller || refs.previousSignature.current === timelineSignature) {
    return;
  }
  refs.previousSignature.current = timelineSignature;
  const forceInitialBottom = shouldForceInitialBottom(refs, timelineSignature);
  if (
    shouldSkipFollow(refs, forceInitialBottom, timelineAnchorMode, scroller)
  ) {
    return;
  }
  const timeout = window.setTimeout(
    () =>
      applyTimelineScroll(
        refs,
        scroller,
        forceInitialBottom,
        timelineAnchorMode,
      ),
    0,
  );
  return () => window.clearTimeout(timeout);
}

// Effect body for the conversation-identity effect below: re-arms the
// one-shot initial scroll (see shouldForceInitialBottom) whenever the chat on
// screen changes. A mount-only ref would miss a sidebar switch between two
// already-loaded chats: ChatWorkspace does not remount for it ("/chats/:id"
// is a param change on the same route), and rehydration replaces the whole
// message log in one step rather than passing through empty, so the
// signature never sees an empty transition to key off.
function armInitialScroll(refs: TimelineScrollRefs) {
  refs.needsInitialScroll.current = true;
}

// Effect body for the scroll that follows sending a turn. Sending is an
// explicit act, so it re-attaches the view wherever the reader had scrolled
// to -- otherwise a follow-up typed while reading back would appear off
// screen with nothing seeming to happen.
function syncSentTurnScroll(
  refs: TimelineScrollRefs,
  isAwaitingAgent: boolean,
) {
  const scroller = refs.scroller.current;
  if (!isAwaitingAgent || !scroller) return;
  const timeout = window.setTimeout(() => scrollToBottom(refs, scroller), 0);
  return () => window.clearTimeout(timeout);
}

// Effect body for the belt-and-suspenders scroll-to-bottom below: fires
// specifically when a session starts, independent of the signature-based
// effect above, since the started-card arriving can coincide with other
// timeline changes.
function syncStartedSessionScroll(
  refs: TimelineScrollRefs,
  startedSession: StartedSession | null,
) {
  const scroller = refs.scroller.current;
  if (!startedSession || !scroller) {
    return;
  }
  const timeout = window.setTimeout(() => scrollToBottom(refs, scroller), 0);
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
 * @param isAwaitingAgent Whether a turn is in flight; its rising edge is the
 *   reader's own send, which re-attaches the view to the bottom.
 * @param conversationId Identity of the chat currently on screen (its
 *   interview id). A change re-arms the initial scroll-to-bottom for
 *   whatever loads next -- see armInitialScroll for why a mount-only ref
 *   isn't enough.
 * @returns The ref to attach to the scrollable timeline container.
 */
export function useChatTimelineScroll(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
  isAwaitingAgent = false,
  conversationId?: string,
) {
  // Scrollable timeline container; scrollTop is driven imperatively below.
  const scrollRef = useRef<HTMLDivElement>(null);
  // Last timeline signature we auto-scrolled for, so the effect below only
  // fires when the timeline actually changed shape/order.
  const previousTimelineSignature = useRef('');
  // Whether the timeline still owes its initial landing at the bottom (see
  // shouldForceInitialBottom / armInitialScroll).
  const needsInitialScroll = useRef(true);
  // Where this hook's own last scroll left the scroller (see
  // isPinnedToBottom), so growth is never mistaken for a reader's gesture.
  const lastAppliedTop = useRef(NO_APPLIED_TOP);
  const refs: TimelineScrollRefs = {
    scroller: scrollRef,
    previousSignature: previousTimelineSignature,
    needsInitialScroll,
    lastAppliedTop,
  };

  const {signature: timelineSignature, anchorMode: timelineAnchorMode} =
    timelineScrollTarget(timelineItems, startedSession);

  // Declared before the signature effect below so that when a conversation
  // switch and its freshly loaded content land in the same commit, the
  // re-arm has already happened by the time that effect reads the flag.
  useEffect(() => armInitialScroll(refs), [conversationId]);

  useEffect(
    () => syncTimelineScroll(refs, timelineSignature, timelineAnchorMode),
    [timelineAnchorMode, timelineSignature],
  );

  useEffect(() => syncSentTurnScroll(refs, isAwaitingAgent), [isAwaitingAgent]);

  // Keyed on the session's id, not the session object: the Agent's start
  // announcement streams into that object fragment by fragment, and this
  // scroll ignores where the reader is by design -- re-running it per
  // fragment would haul a reader who scrolled up back down on every token,
  // the exact behaviour isFollowingBottom exists to prevent. The growth
  // itself reaches the follow-aware effect above through the item's
  // `revision`.
  useEffect(
    () => syncStartedSessionScroll(refs, startedSession),
    [startedSession?.id],
  );

  return scrollRef;
}

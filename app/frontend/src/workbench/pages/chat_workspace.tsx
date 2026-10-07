import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
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
import {Icon} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {HEADER_TITLE_EVENT, NEW_CHAT_EVENT} from '../dom_events';
import {useIsMobile} from '../hooks/dom';
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

// Lazy-load the landing page so chat first paint does not wait for it.
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
  const isMobile = useIsMobile();
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

  // A reopened chat shows nothing until its transcript lands, not the home
  // page underneath it.
  const awaitingTranscript =
    Boolean(chatId) &&
    !session.hasConversation &&
    linkedDraftRecovery.unavailableChatId !== chatId;

  return (
    <div className="reference-workspace grid h-full min-h-full grid-cols-[minmax(0,1fr)] gap-4 [@media(max-width:700px)]:flex [@media(max-width:700px)]:min-h-0 [@media(max-width:700px)]:flex-1 [@media(max-width:700px)]:flex-col">
      <main className="relative flex h-full min-h-0 min-w-0 flex-col [@media(max-width:700px)]:flex-1">
        {session.hasConversation || awaitingTranscript ? (
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
            {/* Phones get the composer only; the landing is a desktop surface. */}
            {!isMobile && (
              <Suspense fallback={null}>
                <HomeLanding />
              </Suspense>
            )}
          </>
        )}
        <ToastPortal toast={toast} />
      </main>
    </div>
  );
}

function focusComposerTextarea() {
  window.requestAnimationFrame(() => {
    const composer = document.querySelector<HTMLTextAreaElement>(
      '.reference-composer textarea',
    );
    composer?.focus();
  });
}

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

// Place the toast above ancestor stacking contexts.
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

// Clear handled navigation state so back/forward and rerenders cannot replay
// new-chat actions.
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

export function useConversationLayout(
  session: ReturnType<typeof useChatSession>,
  navigate: NavigateFunction,
  resetWorkspace: () => void,
  focusComposer: () => void,
  linkedDraftRecovery: LinkedDraftRecovery,
) {
  const composerRef = useRef<HTMLDivElement>(null);

  const timelineItems = buildTimelineItems({
    ...session,
    navigate,
    resetWorkspace,
    focusComposer,
    linkedDraftRecovery,
  });

  const scrollRef = useChatTimelineScroll(
    timelineItems,
    session.startedSession,
    session.isAwaitingAgent,
    session.interview?.id,
  );

  // The overlaid composer needs matching timeline bottom padding as it grows.
  useEffect(
    () => syncComposerHeight(composerRef, scrollRef, session.hasConversation),
    [session.hasConversation, scrollRef],
  );

  return {timelineItems, scrollRef, composerRef};
}

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
        scrollRef={props.scrollRef}
        session={props.session}
        setupDraftMode={props.setupDraftMode}
        connectors={props.connectors}
      />
    </>
  );
}

// Symmetric scrollbar gutters align composer and timeline centers; the measured
// composer height keeps the final message reachable.
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
      className="reference-chat-timeline flex-1 [scrollbar-gutter:stable_both-edges] overflow-x-hidden overflow-y-auto px-4 pt-5 pb-[var(--chat-composer-h,12rem)]"
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

interface ComposerSectionProps {
  composerRef: RefObject<HTMLDivElement | null>;
  scrollRef: RefObject<HTMLDivElement | null>;
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

// A started session asks the run rather than the now-closed interview.
const ASK_RUN_PLACEHOLDER = 'Ask a question about this research session';

// Only the composer catches input; its transparent fade stays click-through
// while messages scroll beneath it. The fade owns spacing, so the composer's
// own top margin would introduce a gap.
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
    <div
      ref={props.composerRef}
      className="pointer-events-none absolute inset-x-0 bottom-0 bg-[linear-gradient(to_top,var(--cosci-bg)_62%,transparent)] px-4 pt-11 pb-8 max-[700px]:pb-[max(0.75rem,env(safe-area-inset-bottom))] [&_.reference-composer]:mt-0 [&>*]:pointer-events-auto"
    >
      <JumpToBottomButton scrollRef={props.scrollRef} />
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

function useScrolledAwayFromBottom(
  scrollRef: RefObject<HTMLDivElement | null>,
): boolean {
  const [away, setAway] = useState(false);
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const update = () => setAway(!isFollowingBottom(scroller));
    update();
    scroller.addEventListener('scroll', update, {passive: true});
    return () => scroller.removeEventListener('scroll', update);
  }, [scrollRef]);
  return away;
}

function JumpToBottomButton({
  scrollRef,
}: {
  scrollRef: RefObject<HTMLDivElement | null>;
}) {
  const away = useScrolledAwayFromBottom(scrollRef);
  if (!away) return null;
  return (
    <button
      type="button"
      aria-label="Jump to latest message"
      title="Jump to latest message"
      className="reference-jump-to-bottom absolute top-0 left-1/2 flex size-9 -translate-x-1/2 items-center justify-center rounded-full border border-cosci-border bg-cosci-bg text-cosci-fg shadow-md hover:bg-cosci-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-th-primary"
      onClick={() => {
        const scroller = scrollRef.current;
        scroller?.scrollTo({top: scroller.scrollHeight, behavior: 'smooth'});
      }}
    >
      <Icon aria-hidden="true" className="text-xl" name="arrow_downward" />
    </button>
  );
}

// Hide sent questions while their replacement arrives; key the chooser by turn
// to reset local selections.
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

// Anchor new draft plans at their top; confirmed plans replace the same turn
// and must not jump again.
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

// Streaming must preserve a reader who deliberately scrolled up.
const FOLLOW_THRESHOLD_PX = 64;

interface TimelineScrollRefs {
  scroller: RefObject<HTMLDivElement | null>;
  previousSignature: RefObject<string>;
  needsInitialScroll: RefObject<boolean>;
  lastAppliedTop: RefObject<number>;
}

const NO_APPLIED_TOP = -1;

// Measure at scroll time: asynchronous scroll events can leave a stale bottom
// flag and undo a reader's gesture.
function isFollowingBottom(scroller: HTMLDivElement): boolean {
  const gap =
    scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  return gap <= FOLLOW_THRESHOLD_PX;
}

// Content growth is not a gesture; unchanged scrollTop since our own scroll
// keeps the timeline pinned.
function isPinnedToBottom(
  refs: TimelineScrollRefs,
  scroller: HTMLDivElement,
): boolean {
  if (scroller.scrollTop === refs.lastAppliedTop.current) return true;
  return isFollowingBottom(scroller);
}

// Read scrollTop back because the browser clamps the assigned value.
function scrollToBottom(
  refs: TimelineScrollRefs,
  scroller: HTMLDivElement,
): void {
  scroller.scrollTop = scroller.scrollHeight;
  refs.lastAppliedTop.current = scroller.scrollTop;
}

const ANCHOR_TOP_INSET_PX = 20;

// Anchor the arriving plan's own top, never the conversation's zero; fall back
// to bottom when its element is absent.
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
  const offset =
    anchor.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  scroller.scrollTop += offset - ANCHOR_TOP_INSET_PX;
  // Only bottom scrolling establishes a pin; recording a top anchor would jump
  // the reader to the plan's Start button.
  refs.lastAppliedTop.current = NO_APPLIED_TOP;
}

// Initial nonempty landing wins over plan anchors and follow guards; reopened
// chats have no reader position to preserve yet.
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

// Bottom landing runs before paint, or a reopened chat flashes its top first;
// plan anchors defer until layout settles so their rectangles are current.
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
  const apply = () =>
    applyTimelineScroll(refs, scroller, forceInitialBottom, timelineAnchorMode);
  if (forceInitialBottom || timelineAnchorMode === 'bottom') {
    apply();
    return;
  }
  const timeout = window.setTimeout(apply, 0);
  return () => window.clearTimeout(timeout);
}

// Lazy Markdown and late attachments grow rows without a signature change;
// keep a pinned reader at the bottom through that growth.
function followContentGrowth(refs: TimelineScrollRefs) {
  const scroller = refs.scroller.current;
  const column = scroller?.firstElementChild;
  if (!scroller || !column || typeof ResizeObserver === 'undefined') return;
  const observer = new ResizeObserver(() => {
    if (scroller.scrollTop === refs.lastAppliedTop.current) {
      scrollToBottom(refs, scroller);
    }
  });
  observer.observe(column);
  return () => observer.disconnect();
}

// Conversation switches do not remount the workspace or pass through empty;
// rearm initial scrolling by identity.
function armInitialScroll(refs: TimelineScrollRefs) {
  refs.needsInitialScroll.current = true;
}

// Sending is an explicit act that reattaches the timeline so the reply cannot
// arrive off screen.
function syncSentTurnScroll(
  refs: TimelineScrollRefs,
  isAwaitingAgent: boolean,
) {
  const scroller = refs.scroller.current;
  if (!isAwaitingAgent || !scroller) return;
  const timeout = window.setTimeout(() => scrollToBottom(refs, scroller), 0);
  return () => window.clearTimeout(timeout);
}

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

export function useChatTimelineScroll(
  timelineItems: TimelineItem[],
  startedSession: StartedSession | null,
  isAwaitingAgent = false,
  conversationId?: string,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousTimelineSignature = useRef('');
  const needsInitialScroll = useRef(true);
  const lastAppliedTop = useRef(NO_APPLIED_TOP);
  const refs: TimelineScrollRefs = {
    scroller: scrollRef,
    previousSignature: previousTimelineSignature,
    needsInitialScroll,
    lastAppliedTop,
  };

  const {signature: timelineSignature, anchorMode: timelineAnchorMode} =
    timelineScrollTarget(timelineItems, startedSession);

  // Rearm before the signature effect when navigation and loaded content land
  // in the same commit.
  useLayoutEffect(() => armInitialScroll(refs), [conversationId]);

  useLayoutEffect(
    () => syncTimelineScroll(refs, timelineSignature, timelineAnchorMode),
    [timelineAnchorMode, timelineSignature],
  );

  // The scroller mounts with the first conversation content.
  const hasContent = timelineItems.length > 0;
  useEffect(() => followContentGrowth(refs), [conversationId, hasContent]);

  useEffect(() => syncSentTurnScroll(refs, isAwaitingAgent), [isAwaitingAgent]);

  // Key this forced scroll by session id; announcement fragments must not
  // repeatedly override a reader's position.
  useEffect(
    () => syncStartedSessionScroll(refs, startedSession),
    [startedSession?.id],
  );

  return scrollRef;
}

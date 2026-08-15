import {Fragment, type RefObject, useEffect, useRef} from 'react';
import {type NavigateFunction} from 'react-router-dom';
import {type useChatSession} from '../hooks/use_chat_session';
import {
  CHAT_COLUMN_CLASSES,
  CHAT_COMPOSER_CLASSES,
  CHAT_TIMELINE_CLASSES,
} from './chat_setup_classes';
import {Composer} from './chat_composer';
import {type ConnectorToggleProps} from './chat_composer_connectors';
import {buildTimelineItems, type TimelineItem} from './chat_workspace_timeline';
import {useChatTimelineScroll} from './chat_workspace_scroll';

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
    session.isAwaitingAgent,
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
    | 'startedSession'
    | 'handleSubmit'
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

// Props for ComposerSection, named at module level per the destructured
// prop signature otherwise pushing the component past the line cap.
interface ComposerSectionProps {
  composerRef: RefObject<HTMLDivElement | null>;
  session: Pick<
    ReturnType<typeof useChatSession>,
    'input' | 'setInput' | 'isStarting' | 'startedSession' | 'handleSubmit'
  >;
  setupDraftMode: boolean;
  connectors: ConnectorToggleProps;
}

// Overlaid, non-scrolling composer; setupDraftMode swaps its placeholder
// copy while a draft/confirmed spec or started session is in view, busy
// blocks submits while starting, and a started session locks the composer
// outright — its interview is completed server-side, so the only way back to
// a live composer is the session reset (new chat).
function ComposerSection(props: ComposerSectionProps) {
  const {input, setInput, isStarting, startedSession, handleSubmit} =
    props.session;
  return (
    <div ref={props.composerRef} className={CHAT_COMPOSER_CLASSES}>
      <div className={CHAT_COLUMN_CLASSES}>
        <Composer
          input={input}
          setInput={setInput}
          setupDraftMode={props.setupDraftMode}
          busy={isStarting}
          disabled={Boolean(startedSession)}
          autoFocus
          connectors={props.connectors}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
}

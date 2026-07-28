import {Link} from 'react-router-dom';
import {type ChatSummary} from '@/api/runs';
import {Icon} from '@/components/icon';
import {conciseTitle} from '@/lib/text';
import {TruncatedLabel} from './components/truncated_label';
import {useFittingRows} from './hooks/use_fitting_rows';
import {useOverflowing} from './hooks/use_overflowing';
import {tabPath} from './run_tabs';
import {tooltipClassNames} from './tooltip';

const SIDE_HEADING_CLASSES = 'ucs-side-heading';

const CHAT_LIST_CLASSES = 'ucs-chat-list';

// Applied only while the list has more chats than the rail can show, since it
// turns the list into a scroll container (which clips its tooltips).
const CHAT_LIST_SCROLLABLE_CLASSES = 'ucs-chat-list--scrollable';

const CHAT_HISTORY_LINK_CLASSES = 'ucs-chat-link';

const CHAT_HISTORY_LINK_ACTIVE_CLASSES = 'ucs-chat-link--active';

const CHAT_HISTORY_LABEL_CLASSES = 'ucs-chat-label';

const CHAT_HISTORY_MORE_CLASSES = 'ucs-chat-more';

/**
 * The chat-list state the rail renders, threaded whole through NavRail so
 * each level passes one value instead of five.
 */
export interface ChatRailData {
  chats: ChatSummary[];
  /** The chat being viewed on /chats/:id, if any. */
  activeChatId: string | undefined;
  /** The run being viewed on /runs/:id, so its chat stays highlighted. */
  activeRunId: string | undefined;
  showAllChats: boolean;
  onToggleShowAllChats: () => void;
}

// Whether a chat row is the one currently being viewed -- either opened
// directly, or through the run it started.
function isActiveChat(chat: ChatSummary, rail: ChatRailData): boolean {
  if (rail.activeChatId) return chat.id === rail.activeChatId;
  return Boolean(chat.run_id) && chat.run_id === rail.activeRunId;
}

/**
 * Where a chat row leads: the stage its session has actually reached.
 *
 * A session that has started a run has moved past its conversation, so the
 * row opens the run -- which is the live progress view while it executes
 * and the report once it lands, chosen by the run page itself. Reopening
 * the transcript instead put every session, running or long finished, back
 * at the same settled prompt and made the rail read as a list of drafts.
 * Only a chat that never started a run opens the conversation, and the
 * run's own back arrow returns there (see ReportTitlebar).
 */
function chatPath(chat: ChatSummary): string {
  return chat.run_id ? tabPath(chat.run_id, undefined) : `/chats/${chat.id}`;
}

// One row in the "Chats" list: the chat's generated title, falling back to a
// concise clause of the scientist's challenge.
function ChatHistoryLink({
  chat,
  isActive,
}: {
  chat: ChatSummary;
  isActive: boolean;
}) {
  return (
    <Link
      data-fitting-row=""
      to={chatPath(chat)}
      className={tooltipClassNames({
        className: isActive
          ? `${CHAT_HISTORY_LINK_CLASSES} ${CHAT_HISTORY_LINK_ACTIVE_CLASSES}`
          : CHAT_HISTORY_LINK_CLASSES,
        placement: 'right',
        wrap: true,
      })}
      aria-current={isActive ? 'page' : undefined}
      data-tooltip={chat.challenge}
    >
      <TruncatedLabel
        className={CHAT_HISTORY_LABEL_CLASSES}
        text={chat.title?.trim() || conciseTitle(chat.challenge)}
      />
    </Link>
  );
}

// The "Show more"/"Show less" toggle at the bottom of the chat list.
function ShowMoreChatsButton({
  showAllChats,
  onToggle,
}: {
  showAllChats: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={CHAT_HISTORY_MORE_CLASSES}
      onClick={onToggle}
    >
      {showAllChats ? 'Show less' : 'Show more'}
      <Icon
        aria-hidden="true"
        name={showAllChats ? 'expand_less' : 'expand_more'}
      />
    </button>
  );
}

// The scrollable chat list itself, plus the "Show more"/"Show less" toggle
// when the history exceeds what fits. Split out of ChatHistorySidebar so the
// overflow-tracking ref/state (only ever read by this list) stays local to
// the piece that uses it.
interface ChatListProps {
  visibleChats: ChatSummary[];
  rail: ChatRailData;
  hasExtraChats: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
}

function ChatList({visibleChats, rail, hasExtraChats, listRef}: ChatListProps) {
  // Only scroll the list when the rail cannot fit it. A scroll container clips
  // its content even with no scrollbar showing, which would cut off the
  // chat-link tooltips escaping to the right.
  const [chatListRef, chatListOverflows] = useOverflowing<HTMLDivElement>();

  return (
    <div
      // One element, two measurements: the overflow probe decides whether it
      // scrolls, the fitting probe (owned by the parent) decides how many rows
      // it is handed.
      ref={node => {
        chatListRef.current = node;
        listRef.current = node;
      }}
      className={
        chatListOverflows
          ? `${CHAT_LIST_CLASSES} ${CHAT_LIST_SCROLLABLE_CLASSES}`
          : CHAT_LIST_CLASSES
      }
    >
      {visibleChats.map(chat => (
        <ChatHistoryLink
          key={chat.id}
          chat={chat}
          isActive={isActiveChat(chat, rail)}
        />
      ))}
      {hasExtraChats && (
        <ShowMoreChatsButton
          showAllChats={rail.showAllChats}
          onToggle={rail.onToggleShowAllChats}
        />
      )}
    </div>
  );
}

/**
 * The "Chats" section of the rail: the chat list, capped to what the rail
 * actually has room for until expanded, with the active chat highlighted.
 *
 * @param sideContentClasses The rail's open/collapsed section classes, passed
 *   in so this module stays independent of the rail's variant table.
 * @param rail The chats, the expansion flag, and what to highlight.
 */
export function ChatHistorySidebar({
  sideContentClasses,
  rail,
}: {
  sideContentClasses: string;
  rail: ChatRailData;
}) {
  const {containerRef, listRef, visibleCount} = useFittingRows<
    HTMLDivElement,
    HTMLDivElement
  >();
  const visibleChats = rail.showAllChats
    ? rail.chats
    : rail.chats.slice(0, visibleCount);
  const hasExtraChats = rail.chats.length > visibleChats.length;

  return (
    <div ref={containerRef} className={sideContentClasses}>
      <p className={SIDE_HEADING_CLASSES}>Chats</p>
      <ChatList
        visibleChats={visibleChats}
        rail={rail}
        hasExtraChats={hasExtraChats || rail.showAllChats}
        listRef={listRef}
      />
    </div>
  );
}

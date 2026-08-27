import {Link} from 'react-router-dom';
import {type ChatSummary} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from './classes';
import {
  HEADER_ACCENT_PILL_CLASSES,
  HEADER_CONTROL_ICON_CLASSES,
} from './layout_primitives';
import {useRecordSessionSide} from './layout_session_memory';
import {tabPath} from './run_tabs';

/**
 * The two halves of one research session and which of them is on screen.
 *
 * A session that has started a run keeps both: the conversation it was
 * specified in, and the run's live progress/report surface. Every route into
 * the session lands on one half (the rail and the home cards both open the
 * run), so this is what carries the reader to the other.
 */
export interface SessionSwitchData {
  chatId: string;
  runId: string;
  active: 'chat' | 'results';
}

// The chat record the current route belongs to: matched by id on a chat
// route, by the run it started on a run route, and nothing at all on a route
// that is neither (a run id is never matched against a null run_id).
function sessionChat(
  chats: readonly ChatSummary[],
  activeChatId: string | undefined,
  activeRunId: string | undefined,
): ChatSummary | undefined {
  if (activeChatId) return chats.find(entry => entry.id === activeChatId);
  if (activeRunId) return chats.find(entry => entry.run_id === activeRunId);
  return undefined;
}

/**
 * The session the current route is one half of, or null when there is no
 * other half to switch to.
 *
 * Resolved through the chat list either way: on a chat route by id, on a run
 * route by the run it started. A chat that has not started a run has nothing
 * to switch to, and neither does a run opened before the chat history has
 * loaded -- the switch simply appears once it does.
 *
 * @param chats The loaded chat history.
 * @param activeChatId The chat id on /chats/:id, if the route is one.
 * @param activeRunId The run id on /runs/:id, if the route is one.
 * @returns Both halves plus the active one, or null.
 */
export function sessionSwitchData(
  chats: readonly ChatSummary[],
  activeChatId: string | undefined,
  activeRunId: string | undefined,
): SessionSwitchData | null {
  const chat = sessionChat(chats, activeChatId, activeRunId);
  if (!chat?.run_id) return null;
  return {
    chatId: chat.id,
    runId: chat.run_id,
    active: activeChatId ? 'chat' : 'results',
  };
}

// The switch's two sides, in display order.
const SWITCH_SIDES: {
  side: 'chat' | 'results';
  icon: IconName;
  label: string;
}[] = [
  {side: 'chat', icon: 'forum', label: 'Chat'},
  {side: 'results', icon: 'lab_profile', label: 'Results'},
];

// The track: the same accent-pill chrome as the Logs trigger (bg, height,
// radius, typography), just gridded into two equal halves instead of one
// button's worth of content -- see HEADER_ACCENT_PILL_CLASSES.
const SWITCH_TRACK_CLASSES = joinClasses(
  'ucs-session-switch relative box-border grid grid-cols-2 gap-[0.2rem] p-[0.2rem]',
  HEADER_ACCENT_PILL_CLASSES,
);

// One side's chrome, sans the active/inactive background. Both sides share
// the pill's own accent text color -- the highlight below, not a dimmed
// label, is what marks which one is current.
const SWITCH_SIDE_CLASSES =
  'ucs-session-switch-side relative z-[1] flex h-full min-w-0 ' +
  'items-center justify-center gap-[0.35rem] rounded-full px-[0.7rem] ' +
  'no-underline hover:bg-cosci-logs-accent-hover ' +
  'focus-visible:bg-cosci-logs-accent-hover';

// The active side additionally carries the same hover tint permanently --
// the Logs pill's own "engaged" look (see [&[aria-expanded=true]] in
// headerControlButtonClasses), reused here to mean "this is where you are".
const SWITCH_SIDE_ACTIVE_CLASSES = joinClasses(
  SWITCH_SIDE_CLASSES,
  'bg-cosci-logs-accent-hover',
);

// Where each side leads. The results side always targets the run's default
// tab rather than remembering the last one: the run page itself chooses
// between the live view and the report, and a remembered tab would be a
// second, staler answer to that question.
function sessionSideHref(session: SessionSwitchData, side: string): string {
  return side === 'chat'
    ? `/chats/${session.chatId}`
    : tabPath(session.runId, undefined);
}

/**
 * The Chat/Results switch shown in the shell header for a session that has
 * both.
 *
 * Two real links rather than a toggle button: each side is a distinct URL
 * that deep-links, opens in a new tab under a modified click, and survives a
 * reload. `aria-current="page"` (not `aria-pressed`) marks the side the
 * reader is already on, matching the navigation it is. Each side also carries
 * an explicit aria-label, because the phone breakpoint hides the visible
 * labels to fit the control into the header (see shell_surface_responsive.css)
 * and an icon-only link would otherwise have no accessible name there.
 *
 * Also records the route's current side as the last-viewed one for this
 * session (see layout_session_memory), so the chat rail and the home recents
 * card both reopen wherever this reader actually left off.
 *
 * @param session The session to switch within; renders nothing without one.
 */
export function SessionSwitch({session}: {session: SessionSwitchData | null}) {
  useRecordSessionSide(session?.runId, session?.chatId, session?.active);
  if (!session) return null;
  return (
    <nav className={SWITCH_TRACK_CLASSES} aria-label="Session view">
      {SWITCH_SIDES.map(({side, icon, label}) => {
        const active = side === session.active;
        return (
          <Link
            key={side}
            to={sessionSideHref(session, side)}
            className={
              active ? SWITCH_SIDE_ACTIVE_CLASSES : SWITCH_SIDE_CLASSES
            }
            aria-current={active ? 'page' : undefined}
            aria-label={label}
          >
            <Icon
              aria-hidden="true"
              className={joinClasses(HEADER_CONTROL_ICON_CLASSES, 'flex-none')}
              name={icon}
            />
            <span className="ucs-session-switch-label">{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

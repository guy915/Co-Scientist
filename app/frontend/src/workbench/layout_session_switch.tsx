import {Link} from 'react-router-dom';
import {type ChatSummary} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
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
 * @param session The session to switch within; renders nothing without one.
 */
export function SessionSwitch({session}: {session: SessionSwitchData | null}) {
  if (!session) return null;
  return (
    <nav
      className="ucs-session-switch"
      aria-label="Session view"
      data-active={session.active}
    >
      {/* The moving highlight. A single element the container slides between
          the two halves, rather than a background on each side: only one
          element can animate from where the highlight *was* to where it is
          going, which is the difference between the marker travelling and it
          reappearing on the other side. */}
      <span className="ucs-session-switch-thumb" aria-hidden="true" />
      {SWITCH_SIDES.map(({side, icon, label}) => {
        const active = side === session.active;
        return (
          <Link
            key={side}
            to={sessionSideHref(session, side)}
            className={
              active
                ? 'ucs-session-switch-side ucs-session-switch-side--active'
                : 'ucs-session-switch-side'
            }
            aria-current={active ? 'page' : undefined}
            aria-label={label}
          >
            <Icon
              aria-hidden="true"
              className="ucs-session-switch-icon"
              name={icon}
            />
            <span className="ucs-session-switch-label">{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

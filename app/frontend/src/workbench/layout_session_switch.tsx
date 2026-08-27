import {Link} from 'react-router-dom';
import {type ChatSummary} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses} from './classes';
import {
  HEADER_CONTROL_ICON_CLASSES,
  HEADER_PILL_SHAPE_CLASSES,
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

// The track: the Logs pill's shape (height, radius, typography) gridded into
// two equal halves, but wearing the quiet segmented-control surface rather
// than the accent. The accent marks *which half you are on*; spending it on
// the whole track would leave the highlight nothing to say.
// The track: the Logs pill's own shape (height, radius, typography) with no
// padding of its own, so each half is a full-height pill exactly the size of
// the Logs trigger rather than a smaller one inset inside a taller box. It
// wears the recents card's own chip surface (--cosci-recent-meta-bg), which
// is configured light and dark to read as a quiet raised surface on either
// -- unlike the card's body colour, which is plain white in light mode and
// so vanishes into the header.
const SWITCH_TRACK_CLASSES = joinClasses(
  'ucs-session-switch relative box-border inline-grid grid-cols-2 p-0',
  'bg-cosci-recent-meta-bg',
  HEADER_PILL_SHAPE_CLASSES,
);

// One side's chrome, matching the Logs trigger's own gap and padding so the
// two are the same control at the same size. The colour is set here, on the
// link itself, and not inherited from the track: these are real <a>
// elements, and the user-agent rule for a visited link outranks an inherited
// colour, which painted both halves browser-purple once either had been
// followed. The fill is the sliding highlight behind them, never a
// background on the side itself -- only one element can travel from where
// the marker was to where it is going.
const SWITCH_SIDE_BASE_CLASSES =
  'ucs-session-switch-side relative z-[1] flex h-full min-w-0 items-center ' +
  'justify-center gap-[0.45rem] rounded-full px-[0.72rem] no-underline';

const SWITCH_SIDE_CLASSES = joinClasses(
  SWITCH_SIDE_BASE_CLASSES,
  'text-cosci-shell-icon',
);

// The side the reader is on: the text colour that reads against the
// highlight arriving under it.
const SWITCH_SIDE_ACTIVE_CLASSES = joinClasses(
  SWITCH_SIDE_BASE_CLASSES,
  'ucs-session-switch-side--active text-cosci-logs-accent-fg',
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
  useRecordSessionSide(session?.runId, session?.active);
  if (!session) return null;
  return (
    <nav
      className={SWITCH_TRACK_CLASSES}
      aria-label="Session view"
      data-active={session.active}
    >
      {/* The moving highlight: one element the track slides between its two
          halves, rather than a background on each side. Only a single
          element can animate from where the marker *was* to where it is
          going, which is the difference between it travelling and it
          reappearing on the other side. */}
      <span className="ucs-session-switch-thumb" aria-hidden="true" />
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

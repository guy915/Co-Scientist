import {Link} from 'react-router-dom';
import type {ChatSummary} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses, tooltipClassNames} from './classes';
import {
  HEADER_CONTROL_ICON_CLASSES,
  HEADER_PILL_SHAPE_CLASSES,
} from './layout_primitives';
import {tabPath} from './run_tabs';
import {useEffect} from 'react';

export interface SessionSwitchData {
  chatId: string;
  runId: string;
  active: 'chat' | 'results';
}

function sessionChat(
  chats: readonly ChatSummary[],
  activeChatId: string | undefined,
  activeRunId: string | undefined,
): ChatSummary | undefined {
  if (activeChatId) return chats.find(entry => entry.id === activeChatId);
  if (activeRunId) return chats.find(entry => entry.run_id === activeRunId);
  return undefined;
}

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

const SWITCH_SIDES: {
  side: 'chat' | 'results';
  icon: IconName;
  label: string;
  tooltip: string;
}[] = [
  {
    side: 'chat',
    icon: 'forum',
    label: 'Chat',
    tooltip: 'Ask questions about this session',
  },
  {
    side: 'results',
    icon: 'lab_profile',
    label: 'Results',
    tooltip: 'View research progress and results',
  },
];

// Quiet raised track colors remain visible in both themes; accent belongs to
// the selected half rather than the whole switch.
const SWITCH_TRACK_CLASSES = joinClasses(
  'ucs-session-switch relative box-border inline-grid grid-cols-2 p-0',
  'bg-cosci-recent-meta-bg',
  HEADER_PILL_SHAPE_CLASSES,
);

// Set link color directly because visited-link browser rules beat inherited
// color; one moving highlight owns the fill.
const SWITCH_SIDE_BASE_CLASSES =
  'ucs-session-switch-side relative z-[1] flex h-full min-w-0 items-center ' +
  'justify-center gap-[0.45rem] rounded-full px-[0.72rem] no-underline';

const SWITCH_SIDE_CLASSES = joinClasses(
  SWITCH_SIDE_BASE_CLASSES,
  'text-cosci-shell-icon',
);

const SWITCH_SIDE_ACTIVE_CLASSES = joinClasses(
  SWITCH_SIDE_BASE_CLASSES,
  'ucs-session-switch-side--active text-cosci-logs-accent-fg',
);

// Results use the default tab; the run page owns live-progress/report selection.
function sessionSideHref(session: SessionSwitchData, side: string): string {
  return side === 'chat'
    ? `/chats/${session.chatId}`
    : tabPath(session.runId, undefined);
}

// Real links preserve deep/new-tab navigation; explicit names survive hidden
// phone labels, and aria-current marks navigation rather than a pressed button.
export function SessionSwitch({session}: {session: SessionSwitchData | null}) {
  useRecordSessionSide(session?.runId, session?.active);
  if (!session) return null;
  return (
    <nav
      className={SWITCH_TRACK_CLASSES}
      aria-label="Session view"
      data-active={session.active}
    >
      {/* A single highlight can travel between sides; independent backgrounds can only reappear. */}
      <span className="ucs-session-switch-thumb" aria-hidden="true" />
      {SWITCH_SIDES.map(({side, icon, label, tooltip}) => {
        const active = side === session.active;
        return (
          <Link
            key={side}
            to={sessionSideHref(session, side)}
            className={tooltipClassNames({
              className: active
                ? SWITCH_SIDE_ACTIVE_CLASSES
                : SWITCH_SIDE_CLASSES,
              placement: 'bottom',
            })}
            data-tooltip={tooltip}
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

export type SessionSide = 'chat' | 'results';

// Run ID is the shared identity available to both conversation rows and run
// cards.
const STORAGE_PREFIX = 'cosci:session-side:';

// New sessions inherit the reader’s last switch position unless they have their
// own memory.
const LAST_SIDE_KEY = 'cosci:session-side';

function isSide(value: unknown): value is SessionSide {
  return value === 'chat' || value === 'results';
}

function read(key: string): SessionSide | undefined {
  try {
    const raw = window.localStorage.getItem(key);
    return isSide(raw) ? raw : undefined;
  } catch {
    return undefined;
  }
}

export function preferredSessionSide(
  runId: string | undefined,
): SessionSide | undefined {
  if (!runId) return undefined;
  return read(STORAGE_PREFIX + runId) ?? read(LAST_SIDE_KEY);
}

export function writeSessionSide(runId: string, side: SessionSide): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + runId, side);
    window.localStorage.setItem(LAST_SIDE_KEY, side);
  } catch {
    // Disabled/full storage must not block session navigation.
  }
}

// Record the actual landed route, including deep links and history clicks,
// rather than only explicit switch actions.
export function useRecordSessionSide(
  runId: string | undefined,
  side: SessionSide | undefined,
): void {
  useEffect(() => {
    if (runId && side) writeSessionSide(runId, side);
  }, [runId, side]);
}

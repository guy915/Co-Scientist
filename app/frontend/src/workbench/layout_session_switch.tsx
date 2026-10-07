import type {ChatSummary} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {joinClasses, tooltipClassNames} from './classes';
import {TabNav, TabNavLink} from '@/shared/ui';
import {HEADER_CONTROL_ICON_CLASSES} from './layout_primitives';
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
    // One highlight travels between the sides instead of each side's fill
    // vanishing and reappearing.
    <TabNav
      label="Session view"
      variant="pill"
      current={session.active}
      layoutClassName="ucs-session-switch h-[2.35rem] min-w-max text-[0.88rem] font-semibold"
    >
      {SWITCH_SIDES.map(({side, icon, label, tooltip}) => (
        <TabNavLink
          key={side}
          variant="pill"
          to={sessionSideHref(session, side)}
          current={side === session.active}
          className={tooltipClassNames({placement: 'bottom'})}
          data-tooltip={tooltip}
          aria-label={label}
        >
          <Icon
            aria-hidden="true"
            className={joinClasses(HEADER_CONTROL_ICON_CLASSES, 'flex-none')}
            name={icon}
          />
          <span className="[@media(max-width:700px)]:hidden">{label}</span>
        </TabNavLink>
      ))}
    </TabNav>
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

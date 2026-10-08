import {useEffect} from 'react';
import {useLocation} from 'react-router-dom';
import {chatPath, runPath} from '@/shared/lib/routes';
import {
  readStorage,
  STORAGE_KEYS,
  writeStorage,
} from '@/shared/lib/safe_storage';

export type SessionSide = 'chat' | 'results';

// Run ID is the shared identity available to both conversation rows and run
// cards.
const STORAGE_PREFIX = STORAGE_KEYS.sessionSidePrefix;

// New sessions inherit the reader’s last switch position unless they have their
// own memory.
const LAST_SIDE_KEY = STORAGE_KEYS.lastSessionSide;

const TAB_PREFIX = STORAGE_KEYS.sessionTabPrefix;

function isSide(value: unknown): value is SessionSide {
  return value === 'chat' || value === 'results';
}

function read(key: string): SessionSide | undefined {
  const raw = readStorage('local', key);
  return isSide(raw) ? raw : undefined;
}

export function preferredSessionSide(
  runId: string | undefined,
): SessionSide | undefined {
  if (!runId) return undefined;
  return read(STORAGE_PREFIX + runId) ?? read(LAST_SIDE_KEY);
}

// Disabled or full storage must not block session navigation.
export function writeSessionSide(runId: string, side: SessionSide): void {
  writeStorage('local', STORAGE_PREFIX + runId, side);
  writeStorage('local', LAST_SIDE_KEY, side);
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

// Results reopen on the tab last viewed for that run; runPath falls back to
// the default tab for an unknown or missing one.
export function resultsPath(runId: string): string {
  return runPath(runId, readStorage('local', TAB_PREFIX + runId) ?? undefined);
}

// Every way back to a run (sidebar, recents, the switch) lands where the
// reader left it: the chat, or the Results tab.
export function sessionEntryPath(
  runId: string,
  chatId: string | undefined,
): string {
  return chatId && preferredSessionSide(runId) === 'chat'
    ? chatPath(chatId)
    : resultsPath(runId);
}

// Runs without a chat have no session switch side, but still keep their tab.
export function useRecordRunTab(): void {
  const {pathname} = useLocation();
  useEffect(() => {
    const [, section, runId, tab] = pathname.split('/');
    if (section === 'runs' && runId && tab) {
      writeStorage('local', TAB_PREFIX + runId, tab);
    }
  }, [pathname]);
}

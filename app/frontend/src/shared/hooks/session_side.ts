import {useEffect} from 'react';

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

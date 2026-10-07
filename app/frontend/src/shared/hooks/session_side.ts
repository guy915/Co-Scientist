import {useEffect} from 'react';
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

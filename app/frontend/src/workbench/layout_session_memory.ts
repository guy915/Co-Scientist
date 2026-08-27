import {useEffect} from 'react';

/** Which half of a session was last on screen. */
export type SessionSide = 'chat' | 'results';

// One localStorage entry per session, keyed by the run id: it is available
// at every entry point that needs to read the memory (a chat row only knows
// the chat once it has started a run, at which point it also has run_id; a
// recents card only knows the run). The chat id rides along in the value so
// a recents card -- which has no chat list of its own -- can still build a
// `/chats/:id` href for the chat side without one.
const STORAGE_PREFIX = 'cosci:session-side:';

interface StoredSide {
  chatId: string;
  side: SessionSide;
}

function isStoredSide(value: unknown): value is StoredSide {
  const record = value as Partial<StoredSide> | null;
  return (
    typeof record?.chatId === 'string' &&
    (record.side === 'chat' || record.side === 'results')
  );
}

/**
 * The side last viewed for the session that started `runId`, or undefined
 * with no memory (never started, cleared storage, or a private window that
 * refuses storage) -- callers keep today's default in that case.
 */
export function readSessionSide(runId: string): StoredSide | undefined {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + runId);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return isStoredSide(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

/** Records the side currently on screen for the session that started `runId`. */
export function writeSessionSide(
  runId: string,
  chatId: string,
  side: SessionSide,
): void {
  try {
    const value: StoredSide = {chatId, side};
    window.localStorage.setItem(STORAGE_PREFIX + runId, JSON.stringify(value));
  } catch {
    // Storage disabled (private window, quota): the memory is best-effort.
  }
}

/**
 * Records the route's current side as it changes, so a deep link or a rail
 * click updates the memory exactly like clicking the switch would -- the
 * memory reflects wherever the reader actually lands, not only deliberate
 * switch clicks.
 */
export function useRecordSessionSide(
  runId: string | undefined,
  chatId: string | undefined,
  side: SessionSide | undefined,
): void {
  useEffect(() => {
    if (runId && chatId && side) writeSessionSide(runId, chatId, side);
  }, [runId, chatId, side]);
}

import {useEffect} from 'react';

/** Which half of a session was last on screen. */
export type SessionSide = 'chat' | 'results';

// One entry per session, keyed by the run id -- the one identifier both
// entry points hold (a chat row knows its run once it has started one; a
// recents card knows only the run).
const STORAGE_PREFIX = 'cosci:session-side:';

// The side last viewed in *any* session. The scientist reads the control as
// one switch with a position, not as a per-session preference: flipping to
// Chat and then opening a different session from the recents list and
// landing on Results reads as the switch being ignored. So a session with no
// memory of its own inherits the switch's last position, and only a reader
// who has never touched it gets the old defaults.
const LAST_SIDE_KEY = 'cosci:session-side';

function isSide(value: unknown): value is SessionSide {
  return value === 'chat' || value === 'results';
}

function read(key: string): SessionSide | undefined {
  try {
    const raw = window.localStorage.getItem(key);
    return isSide(raw) ? raw : undefined;
  } catch {
    // Storage disabled (private window, quota): the memory is best-effort.
    return undefined;
  }
}

/**
 * The side to open a session on: its own memory, else wherever the switch
 * was last left, else undefined so the caller keeps its own default.
 *
 * @param runId The run the session started, or undefined for a chat that
 *   has not started one (which has no other half to open).
 */
export function preferredSessionSide(
  runId: string | undefined,
): SessionSide | undefined {
  if (!runId) return undefined;
  return read(STORAGE_PREFIX + runId) ?? read(LAST_SIDE_KEY);
}

/** Records the side on screen, for this session and for the switch itself. */
export function writeSessionSide(runId: string, side: SessionSide): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + runId, side);
    window.localStorage.setItem(LAST_SIDE_KEY, side);
  } catch {
    // As above: best-effort.
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
  side: SessionSide | undefined,
): void {
  useEffect(() => {
    if (runId && side) writeSessionSide(runId, side);
  }, [runId, side]);
}

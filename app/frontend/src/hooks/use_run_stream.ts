import {type Dispatch, type SetStateAction, useEffect, useState} from 'react';
import {clientHeaders, eventsStreamUrl, readSseFrames} from '@/api/runs';
import {forgetSessionIfUnauthorized} from '@/api/runs_http';

/** A single event streamed from a run's SSE timeline. */
export interface StreamEvent {
  seq: number; // monotonically increasing position in the run's event log
  type: string; // event kind, e.g. node/agent lifecycle names from the backend
  payload: Record<string, unknown>; // type-specific body; consumers narrow it
  created_at?: number;
}

/**
 * Live transport state of the stream's connection. 'connecting' is the
 * initial state (and persists while a pre-open attempt retries), 'open'
 * means a response is streaming, 'reconnecting' means a connection that had
 * opened dropped and a new attempt is retrying it, and 'disconnected' means
 * the attempt ended with no retry (an auth or not-found rejection that a
 * retry cannot fix).
 */
export type StreamConnectionState =
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'disconnected';

/** State returned by {@link useRunStream}. */
export interface UseRunStreamResult {
  events: StreamEvent[]; // full ordered timeline received so far
  terminal: boolean; // true once the backend sent the end-of-stream sentinel
  connection: StreamConnectionState; // live transport state
}

// Delay before retrying a dropped or ended connection. Fixed rather than
// backed off: the backend always replays from seq=0 and the batcher below
// dedupes by seq, so a prompt retry is cheap and keeps the UI's "how stale
// is this" story simple. Exported so tests can advance exactly this far
// with fake timers rather than guessing.
export const RECONNECT_DELAY_MS = 2000;

/**
 * Batches StreamEvent arrivals and flushes them into `setEvents` at most once
 * per macrotask, so a replay burst (many pushes in one task) costs a single
 * render instead of one per event. Pulled out of the connection logic below
 * since batching is a separable concern: this factory owns no resource the
 * connection's cleanup needs to reach into directly, only the buffer/timer
 * pair, which it fully encapsulates.
 */
function createEventBatcher(
  setEvents: Dispatch<SetStateAction<StreamEvent[]>>,
) {
  let buffer: StreamEvent[] = [];
  let flushTimer = 0;
  // Seqs already accepted, so a replayed event is dropped instead of
  // re-appended. Every reconnect (including this hook's own fetch retries)
  // replays the whole timeline from seq=0, so without this a dropped
  // connection re-queues it at the end of `events`; `slice(-10)` then
  // surfaces the run's oldest steps as if they were the newest, and the
  // duplicate `seq`s collide as React keys.
  const seen = new Set<number>();

  const flush = () => {
    flushTimer = 0;
    if (buffer.length === 0) return;
    const batch = buffer;
    buffer = [];
    setEvents(prev => [...prev, ...batch]);
  };

  return {
    // Queues an event unless its seq was already accepted; schedules at
    // most one flush at a time (0 means no timer pending).
    push(ev: StreamEvent) {
      if (seen.has(ev.seq)) return;
      seen.add(ev.seq);
      buffer.push(ev);
      if (flushTimer === 0) flushTimer = window.setTimeout(flush, 0);
    },
    // Drains anything still buffered right now, e.g. before marking the
    // stream terminal so no event is lost when it closes.
    flushNow() {
      window.clearTimeout(flushTimer);
      flush();
    },
    // Cancels any pending flush and drops the unflushed buffer without
    // running it, e.g. on cleanup, where a flush would append this run's
    // events to the next run's state.
    cancelPending() {
      window.clearTimeout(flushTimer);
    },
  };
}

/** Outcome of one connection attempt: whether and how to continue. */
type StreamOutcome = 'terminal' | 'retry' | 'fatal';

/** Callbacks a stream connection reports transport and data events to. */
interface StreamConnectionCallbacks {
  onEvent(ev: StreamEvent): void;
  onOpen(): void;
  onTerminal(): void;
}

/** Whether an HTTP status from the events endpoint will not improve on retry. */
function isPermanentStreamFailure(status: number): boolean {
  return status === 401 || status === 403 || status === 404;
}

/**
 * Reads frames off one live, already-OK response until the stream ends
 * (server closed it, or a malformed frame broke parsing -- either way not
 * distinguishable from a plain drop, so both simply trigger a reconnect
 * via `readSseFrames`'s own replay-from-seq=0 contract) or the backend's
 * `_terminal` sentinel arrives.
 */
async function consumeStream(
  res: Response,
  callbacks: StreamConnectionCallbacks,
  isCancelled: () => boolean,
): Promise<StreamOutcome> {
  try {
    for await (const ev of readSseFrames<StreamEvent>(res)) {
      if (isCancelled()) return 'terminal';
      // '_terminal' is a synthetic end-of-stream sentinel from the
      // backend, not a real run event; it is consumed here and never
      // surfaced.
      if (ev.type === '_terminal') {
        callbacks.onTerminal();
        return 'terminal';
      }
      callbacks.onEvent(ev);
    }
  } catch {
    return 'retry';
  }
  return 'retry';
}

/**
 * Opens one connection attempt to a run's events endpoint over `fetch` --
 * not `EventSource`, which cannot attach the `X-Client-ID`/`Authorization`
 * header `clientHeaders()` builds, forcing identity into the URL instead.
 */
async function connectOnce(
  runId: string,
  signal: AbortSignal,
  callbacks: StreamConnectionCallbacks,
  isCancelled: () => boolean,
): Promise<StreamOutcome> {
  let res: Response;
  try {
    res = await fetch(eventsStreamUrl(runId), {
      headers: clientHeaders(),
      signal,
    });
  } catch {
    return 'retry';
  }
  if (!res.ok || !res.body) {
    forgetSessionIfUnauthorized(res);
    return isPermanentStreamFailure(res.status) ? 'fatal' : 'retry';
  }
  callbacks.onOpen();
  return consumeStream(res, callbacks, isCancelled);
}

/** Whether the loop should stop or retry after one attempt's outcome. */
type LoopAction = 'stop' | 'retry';

/**
 * Reports the transport-state consequence of one attempt's outcome and says
 * whether the loop should retry. Split out of the loop below purely to keep
 * that function's branching within the repo's complexity ceiling.
 */
function reportOutcome(
  outcome: StreamOutcome,
  cancelled: boolean,
  opened: boolean,
  onTransportChange: (state: Exclude<StreamConnectionState, 'open'>) => void,
): LoopAction {
  // A cancel that lands while this attempt was in flight (e.g. unmount
  // during an open stream) must not report a transport state or start a
  // retry timer after the caller has already stopped listening.
  if (cancelled || outcome === 'terminal') return 'stop';
  if (outcome === 'fatal') {
    onTransportChange('disconnected');
    return 'stop';
  }
  onTransportChange(opened ? 'reconnecting' : 'connecting');
  return 'retry';
}

/**
 * Drives one run's SSE subscription: connects, replays+tails, and
 * reconnects on any drop that is not a permanent auth/not-found rejection.
 * Pulled out of the effect below for the same reason `createEventBatcher`
 * is: it owns resources (the abort controller, the retry timer) the
 * effect's cleanup must reach into, fully encapsulated behind `stop()`.
 */
function createStreamConnection(
  runId: string,
  callbacks: StreamConnectionCallbacks & {
    onTransportChange(state: Exclude<StreamConnectionState, 'open'>): void;
  },
) {
  let cancelled = false;
  let opened = false;
  let controller: AbortController | null = null;
  let retryTimer = 0;
  const dataCallbacks: StreamConnectionCallbacks = {
    onEvent: callbacks.onEvent,
    onTerminal: callbacks.onTerminal,
    onOpen: () => {
      opened = true;
      callbacks.onOpen();
    },
  };

  async function loop(): Promise<void> {
    while (!cancelled) {
      controller = new AbortController();
      const outcome = await connectOnce(
        runId,
        controller.signal,
        dataCallbacks,
        () => cancelled,
      );
      controller.abort();
      const action = reportOutcome(
        outcome,
        cancelled,
        opened,
        callbacks.onTransportChange,
      );
      if (action === 'stop') return;
      await new Promise<void>(resolve => {
        retryTimer = window.setTimeout(resolve, RECONNECT_DELAY_MS);
      });
    }
  }

  return {
    start(): void {
      void loop();
    },
    stop(): void {
      cancelled = true;
      controller?.abort();
      window.clearTimeout(retryTimer);
    },
  };
}

/**
 * Subscribe to /api/runs/{id}/events. Always replays from seq=0 so the
 * UI hydrates the entire timeline on mount, even after a refresh.
 *
 * Connection state is surfaced in `connection`: a dropped or stalled stream
 * reconnects on its own, but silently -- before this was tracked, that left
 * the page frozen yet looking healthy. Reconnects keep the batching/dedupe
 * semantics above (the backend replays from seq=0 and the seq set drops the
 * duplicates). The deliberate stop on the terminal sentinel leaves the last
 * state in place; `terminal` is the completion signal, not `connection`.
 */
export function useRunStream(runId: string | null): UseRunStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [terminal, setTerminal] = useState(false);
  const [connection, setConnection] =
    useState<StreamConnectionState>('connecting');

  useEffect(() => {
    if (!runId) return; // nothing to stream until a run is selected
    // Reset state when switching runs: the previous run's timeline must not
    // bleed into the new subscription (which replays from seq=0 anyway).
    setEvents([]);
    setTerminal(false);
    setConnection('connecting');

    const batcher = createEventBatcher(setEvents);
    const conn = createStreamConnection(runId, {
      onEvent: ev => batcher.push(ev),
      onOpen: () => setConnection('open'),
      onTerminal: () => {
        batcher.flushNow();
        setTerminal(true);
      },
      onTransportChange: state => setConnection(state),
    });
    conn.start();

    return () => {
      batcher.cancelPending();
      conn.stop();
    };
    // Re-subscribe only when runId changes; other setters are stable.
  }, [runId]);
  return {events, terminal, connection};
}

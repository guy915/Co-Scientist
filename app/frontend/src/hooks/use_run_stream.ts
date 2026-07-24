import {type Dispatch, type SetStateAction, useEffect, useState} from 'react';
import {eventsStreamUrl} from '@/api/runs';

/** A single event streamed from a run's SSE timeline. */
export interface StreamEvent {
  seq: number; // monotonically increasing position in the run's event log
  type: string; // event kind, e.g. node/agent lifecycle names from the backend
  payload: Record<string, unknown>; // type-specific body; consumers narrow it
  created_at?: number;
}

/** State returned by {@link useRunStream}. */
export interface UseRunStreamResult {
  events: StreamEvent[]; // full ordered timeline received so far
  terminal: boolean; // true once the backend sent the end-of-stream sentinel
}

/**
 * Batches StreamEvent arrivals and flushes them into `setEvents` at most once
 * per macrotask, so a replay burst (many onmessage calls in one task) costs a
 * single render instead of one per event. Pulled out of the connection
 * effect below since batching is a separable concern from the EventSource
 * wiring itself: this factory owns no resource that the effect's cleanup
 * needs to reach into directly, only the buffer/timer pair, which it fully
 * encapsulates.
 */
function createEventBatcher(
  setEvents: Dispatch<SetStateAction<StreamEvent[]>>,
) {
  let buffer: StreamEvent[] = [];
  let flushTimer = 0;
  // Seqs already accepted, so a replayed event is dropped instead of
  // re-appended. EventSource reconnects transparently and the backend
  // always replays from seq=0, so without this a dropped connection
  // re-queues the whole timeline at the end of `events`; `slice(-10)`
  // then surfaces the run's oldest steps as if they were the newest,
  // and the duplicate `seq`s collide as React keys.
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

/**
 * Subscribe to /api/runs/{id}/events. Always replays from seq=0 so the
 * UI hydrates the entire timeline on mount, even after a refresh.
 *
 * Connection drops are not surfaced: EventSource reconnects on its own, and
 * the terminal sentinel is the only signal consumers act on.
 */
export function useRunStream(runId: string | null): UseRunStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [terminal, setTerminal] = useState(false);
  useEffect(() => {
    if (!runId) return; // nothing to stream until a run is selected
    // Reset state when switching runs: the previous run's timeline must not
    // bleed into the new subscription (which replays from seq=0 anyway).
    setEvents([]);
    setTerminal(false);

    const es = new EventSource(eventsStreamUrl(runId));
    const batcher = createEventBatcher(setEvents);

    es.onmessage = msg => {
      try {
        const ev = JSON.parse(msg.data) as StreamEvent;
        // '_terminal' is a synthetic end-of-stream sentinel from the backend,
        // not a real run event; it is consumed here and never surfaced.
        if (ev.type === '_terminal') {
          batcher.flushNow();
          setTerminal(true);
          es.close();
          return;
        }
        batcher.push(ev);
      } catch (e) {
        // A malformed frame is logged and skipped; the stream keeps going.
        console.error('[useRunStream] parse failed', e);
      }
    };

    return () => {
      batcher.cancelPending();
      es.close();
    };
    // Re-subscribe only when runId changes; other setters are stable.
  }, [runId]);
  return {events, terminal};
}

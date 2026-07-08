import {useEffect, useState} from 'react';
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

    // The server replays the full history on connect and each event arrives
    // as its own onmessage macrotask, so appending per message costs one
    // render (and one array copy) per historical event. Buffer arrivals and
    // flush once per timer tick: a replay burst that is already queued drains
    // ahead of the timer, collapsing into a single state update.
    let buffer: StreamEvent[] = [];
    let flushTimer = 0;

    const flush = () => {
      flushTimer = 0;
      if (buffer.length === 0) return;
      const batch = buffer;
      buffer = [];
      setEvents(prev => [...prev, ...batch]);
    };

    es.onmessage = msg => {
      try {
        const ev = JSON.parse(msg.data) as StreamEvent;
        // '_terminal' is a synthetic end-of-stream sentinel from the backend,
        // not a real run event; it is consumed here and never surfaced.
        if (ev.type === '_terminal') {
          // Drain anything still buffered before marking terminal so no
          // event is lost when the stream closes.
          window.clearTimeout(flushTimer);
          flush();
          setTerminal(true);
          es.close();
          return;
        }
        buffer.push(ev);
        // Schedule at most one flush at a time (0 means no timer pending).
        if (flushTimer === 0) flushTimer = window.setTimeout(flush, 0);
      } catch (e) {
        // A malformed frame is logged and skipped; the stream keeps going.
        console.error('[useRunStream] parse failed', e);
      }
    };

    return () => {
      // Cancel any pending flush and drop the unflushed buffer: after cleanup
      // a flush would append this run's events to the next run's state.
      window.clearTimeout(flushTimer);
      es.close();
    };
    // Re-subscribe only when runId changes; other referenced setters are stable.
  }, [runId]);

  return {events, terminal};
}

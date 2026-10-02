import {type Dispatch, type SetStateAction, useEffect, useState} from 'react';
import {
  API_BASE_URL,
  clientHeaders,
  fetchWithSession,
  readSseFrames,
} from '@/api/runs_http';

export interface StreamEvent {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at?: number;
}

/** A permanent auth/not-found rejection disconnects without retrying. */
export type StreamConnectionState =
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'disconnected';

export interface UseRunStreamResult {
  events: StreamEvent[];
  terminal: boolean;
  connection: StreamConnectionState;
}

export const RECONNECT_DELAY_MS = 2000;

/** Batch replay bursts into one render and dedupe reconnects by sequence. */
function createEventBatcher(
  setEvents: Dispatch<SetStateAction<StreamEvent[]>>,
) {
  let buffer: StreamEvent[] = [];
  let flushTimer = 0;
  const seen = new Set<number>();

  const flush = () => {
    flushTimer = 0;
    if (buffer.length === 0) return;
    const batch = buffer;
    buffer = [];
    setEvents(prev => [...prev, ...batch]);
  };

  return {
    push(ev: StreamEvent) {
      if (seen.has(ev.seq)) return;
      seen.add(ev.seq);
      buffer.push(ev);
      if (flushTimer === 0) flushTimer = window.setTimeout(flush, 0);
    },
    flushNow() {
      window.clearTimeout(flushTimer);
      flush();
    },
    cancelPending() {
      window.clearTimeout(flushTimer);
    },
  };
}

/** Replay from seq=0 on mount/reconnect to hydrate the complete timeline. */
export function useRunStream(runId: string | null): UseRunStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [terminal, setTerminal] = useState(false);
  const [connection, setConnection] =
    useState<StreamConnectionState>('connecting');

  useEffect(() => {
    if (!runId) return;
    setEvents([]);
    setTerminal(false);
    setConnection('connecting');

    const batcher = createEventBatcher(setEvents);
    let cancelled = false;
    let opened = false;
    let controller: AbortController | null = null;
    let retryTimer = 0;

    async function connect(): Promise<void> {
      while (!cancelled) {
        controller = new AbortController();
        try {
          const res = await fetchWithSession(
            `${API_BASE_URL}/api/runs/${runId}/events`,
            {headers: clientHeaders(), signal: controller.signal},
          );
          if (cancelled) return;
          if (!res.ok || !res.body) {
            if ([401, 403, 404].includes(res.status)) {
              setConnection('disconnected');
              return;
            }
            throw new Error('Events stream unavailable');
          }
          opened = true;
          setConnection('open');
          for await (const ev of readSseFrames<StreamEvent>(res)) {
            if (cancelled) return;
            if (ev.type === '_terminal') {
              batcher.flushNow();
              setTerminal(true);
              return;
            }
            batcher.push(ev);
          }
        } catch {
          // Drops and malformed frames both reconnect; replay is deduplicated.
        } finally {
          controller.abort();
        }
        if (cancelled) return;
        setConnection(opened ? 'reconnecting' : 'connecting');
        await new Promise<void>(resolve => {
          retryTimer = window.setTimeout(resolve, RECONNECT_DELAY_MS);
        });
      }
    }

    void connect();
    return () => {
      cancelled = true;
      batcher.cancelPending();
      controller?.abort();
      window.clearTimeout(retryTimer);
    };
  }, [runId]);
  return {events, terminal, connection};
}

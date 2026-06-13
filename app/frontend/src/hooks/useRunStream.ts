/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import {useEffect, useRef, useState} from 'react';
import {eventsStreamUrl} from '@/api/runs';

export interface StreamEvent {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at?: number;
}

export interface UseRunStreamResult {
  events: StreamEvent[];
  lastSeq: number;
  isOpen: boolean;
  error: string | null;
  terminal: boolean;
}

/**
 * Subscribe to /api/runs/{id}/events. Always replays from seq=0 so the
 * UI hydrates the entire timeline on mount, even after a refresh.
 */
export function useRunStream(
  runId: string | null,
  after = 0,
): UseRunStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [lastSeq, setLastSeq] = useState(after);
  const [isOpen, setIsOpen] = useState(false);
  const [terminal, setTerminal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!runId) return;
    setEvents([]);
    setLastSeq(after);
    setTerminal(false);
    setError(null);

    const es = new EventSource(eventsStreamUrl(runId, after));
    sourceRef.current = es;

    es.onopen = () => setIsOpen(true);
    es.onerror = () => {
      // Browsers fire onerror on close; we use the terminal flag to suppress
      // false-positive UI errors.
      if (!terminal) setError('Connection lost; events may be incomplete.');
      setIsOpen(false);
    };
    es.onmessage = msg => {
      try {
        const ev = JSON.parse(msg.data) as StreamEvent;
        if (ev.type === '_terminal') {
          setTerminal(true);
          es.close();
          setIsOpen(false);
          return;
        }
        setEvents(prev => [...prev, ev]);
        setLastSeq(prev => Math.max(prev, ev.seq));
      } catch (e) {
        console.error('[useRunStream] parse failed', e);
      }
    };

    return () => {
      es.close();
      sourceRef.current = null;
      setIsOpen(false);
    };
    // Re-subscribe only when runId changes; other referenced setters are stable.
  }, [runId]);

  return {events, lastSeq, isOpen, error, terminal};
}

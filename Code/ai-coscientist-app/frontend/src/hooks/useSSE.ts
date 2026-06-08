import { useEffect, useRef, useState } from "react";

export interface UseSSEOptions {
  url: string;
  onMessage: (event: MessageEvent) => void;
  onError?: (error: Event) => void;
  enabled?: boolean;
}

export type SSEStatus = "connecting" | "open" | "closed";

export interface UseSSEResult {
  status: SSEStatus;
  close: () => void;
}

/**
 * Custom hook for Server-Sent Events (SSE) connection
 *
 * @param options Configuration options for the SSE connection
 * @returns Object containing connection status and close function
 *
 * @example
 * ```tsx
 * const { status, close } = useSSE({
 *   url: 'http://localhost:8008/generate/stream',
 *   onMessage: (event) => {
 *     const data = JSON.parse(event.data);
 *     console.log('Received:', data);
 *   },
 *   onError: (error) => {
 *     console.error('SSE Error:', error);
 *   },
 *   enabled: true
 * });
 * ```
 */
export function useSSE({ url, onMessage, onError, enabled = true }: UseSSEOptions): UseSSEResult {
  const [status, setStatus] = useState<SSEStatus>("closed");
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      setStatus("open");
    };

    eventSource.onmessage = (event) => {
      onMessage(event);
    };

    eventSource.onerror = (error) => {
      setStatus("closed");
      onError?.(error);
      eventSource.close();
    };

    return () => {
      eventSource.close();
      setStatus("closed");
    };
  }, [url, enabled, onMessage, onError]);

  const close = () => {
    eventSourceRef.current?.close();
    setStatus("closed");
  };

  return { status, close };
}

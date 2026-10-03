import {type Dispatch, type SetStateAction} from 'react';
import {makePrefixedId} from '@/lib/client_id';
import {type QaSource} from '@/api/runs';
import {DIAGNOSTIC_EVENT} from '../dom_events';
import {type ChatEntry} from '../pages/chat_timeline_bubble';

/** The chat session's diagnostic-log categories. */
export type DiagnosticStage = 'LIFECYCLE' | 'CHAT';

/**
 * Fires a fire-and-forget diagnostic line for the shell's Logs popover
 * (DiagnosticsControl in layout_diagnostics.tsx listens for this event); a
 * window event keeps the chat session decoupled from the shell component.
 */
export function emitDiagnosticEvent({
  stage,
  runId,
  level = 'info',
  payload = {},
}: {
  stage: DiagnosticStage;
  /**
   * Real run id, when one exists. Deliberately not a title: this is
   * persisted as the record's run_id and served over the logs API, so
   * anything goal-derived here would publish research content.
   */
  runId?: string;
  // The persisted log has no "success" band — the levels are Python's, so
  // an emitted success was only ever stored (and counted) as info.
  level?: 'info' | 'warning' | 'error';
  payload?: Record<string, unknown>;
}) {
  window.dispatchEvent(
    new CustomEvent(DIAGNOSTIC_EVENT, {
      detail: {stage, runId, level, payload},
    }),
  );
}

/** One appended chat bubble, as its callers describe it. */
export interface NewChatMessage {
  role: 'assistant' | 'user';
  content: string;
  /** The Agent's chain of thought for this turn, when it produced one. */
  reasoning?: string;
  /** Epoch seconds; defaults to now. */
  createdAt?: number;
  /** A run Q&A answer's evidence manifest; see `ChatEntry.sources`. */
  sources?: QaSource[];
}

/**
 * Appends a chat bubble; timestamps are epoch seconds (matching the API's
 * created_at convention) and returned so callers can order follow-up entries
 * relative to this one. Takes `setMessages` as an argument instead of closing
 * over hook state so every handler that appends a message can share it without
 * each needing its own copy.
 */
export function appendChatMessage(
  setMessages: Dispatch<SetStateAction<ChatEntry[]>>,
  message: NewChatMessage,
): number {
  const createdAt = message.createdAt ?? Date.now() / 1000;
  setMessages(prev => [
    ...prev,
    {
      id: makePrefixedId(message.role),
      role: message.role,
      content: message.content,
      reasoning: message.reasoning,
      sources: message.sources,
      created_at: createdAt,
    },
  ]);
  return createdAt;
}

/**
 * Wraps a ref holding the latest `HandlerDeps` bag in an object whose
 * enumerable getters delegate to `ref.current`. buildChatHandlers can then be
 * called ONCE (stable handler identities across renders) while every handler
 * — including spreads like `{...handlerDeps}` — still reads the current
 * render's state at call time. The key set is fixed by the initial bag, which
 * is fine: HandlerDeps is a closed interface.
 */
export function liveHandlerDeps<T extends object>(ref: {current: T}): T {
  const live = {} as T;
  for (const key of Object.keys(ref.current) as (keyof T)[]) {
    Object.defineProperty(live, key, {
      enumerable: true,
      get: () => ref.current[key],
    });
  }
  return live;
}

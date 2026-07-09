import {type Dispatch, type SetStateAction} from 'react';
import {makePrefixedId} from '@/lib/id';
import {type ChatEntry} from '../pages/chat_timeline_cards';

/**
 * Fires a fire-and-forget diagnostic line for the shell's Logs popover
 * (DiagnosticsControl in layout_diagnostics.tsx listens for this event); a
 * window event keeps the chat session decoupled from the shell component.
 */
export function emitDiagnosticEvent({
  stage,
  run,
  level = 'info',
  payload = {},
}: {
  stage: string;
  run?: string;
  level?: 'info' | 'success' | 'error';
  payload?: Record<string, unknown>;
}) {
  window.dispatchEvent(
    new CustomEvent('cosci-diagnostic-event', {
      detail: {stage, run, level, payload},
    }),
  );
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
  role: 'assistant' | 'user',
  content: string,
  createdAt = Date.now() / 1000,
): number {
  setMessages(prev => [
    ...prev,
    {
      id: makePrefixedId(role),
      role,
      content,
      created_at: createdAt,
    },
  ]);
  return createdAt;
}

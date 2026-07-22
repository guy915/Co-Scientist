import {render} from '@testing-library/react';
import {vi} from 'vitest';
import {makeMessage as makeSharedMessage} from '@/test_fixtures';
import {ChatBubble, type ChatEntry} from './chat_timeline_bubble';

export function makeMessage(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return makeSharedMessage({content: 'Hello there', ...overrides});
}

export function renderBubble(overrides: Partial<ChatEntry> = {}) {
  const onEdit = vi.fn();
  const onCopyRequest = vi.fn();
  const onRetry = vi.fn();
  const message = makeMessage(overrides);
  const utils = render(
    <ChatBubble
      message={message}
      onEdit={onEdit}
      onCopyRequest={onCopyRequest}
      onRetry={onRetry}
    />,
  );
  return {...utils, onEdit, onCopyRequest, onRetry, message};
}

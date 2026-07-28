import {render} from '@testing-library/react';
import {vi} from 'vitest';
import {makeMessage as makeSharedMessage} from '@/test_fixtures';
import {ChatBubble, type ChatEntry} from './chat_timeline_bubble';

export function makeMessage(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return makeSharedMessage({content: 'Hello there', ...overrides});
}

export function renderBubble(
  overrides: Partial<ChatEntry> = {},
  revisable = true,
) {
  const onSubmitEdit = vi.fn();
  const onCopyRequest = vi.fn();
  const onRetry = vi.fn();
  const message = makeMessage(overrides);
  const utils = render(
    <ChatBubble
      message={message}
      revisable={revisable}
      onSubmitEdit={onSubmitEdit}
      onCopyRequest={onCopyRequest}
      onRetry={onRetry}
    />,
  );
  return {...utils, onSubmitEdit, onCopyRequest, onRetry, message};
}

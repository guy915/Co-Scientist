import {expect, test, vi} from 'vitest';
import {buildChatHandlers} from './chat_session_handlers';
import {makeDeps} from './chat_session_handlers_test_support';
import type {ChatEntry} from '../pages/chat_timeline_cards';
import {makeMessage} from '@/test_fixtures';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {...actual, createInterview: vi.fn(), addInterviewTurn: vi.fn()};
});

test('handleRetryMessage re-appends the message content as a fresh assistant bubble', () => {
  const deps = makeDeps();
  const handlers = buildChatHandlers(deps);

  handlers.handleRetryMessage(
    makeMessage({role: 'assistant', content: 'Reply text'}),
  );

  expect(deps.setMessages).toHaveBeenCalledOnce();
  const updater = vi.mocked(deps.setMessages).mock.calls[0][0] as unknown as (
    prev: ChatEntry[],
  ) => ChatEntry[];
  const next = updater([]);
  expect(next).toHaveLength(1);
  expect(next[0]).toMatchObject({role: 'assistant', content: 'Reply text'});
});

test('handleCopyRequest copies the prompt, and its toast action starts a new chat prefilled with it', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {writeText},
  });
  const deps = makeDeps();
  const handlers = buildChatHandlers(deps);

  await handlers.handleCopyRequest(makeMessage({content: 'Copy me'}));

  expect(writeText).toHaveBeenCalledWith('Copy me');
  expect(deps.setToast).toHaveBeenCalledWith(
    expect.objectContaining({
      message: 'Prompt copied',
      action: expect.objectContaining({label: 'Start new chat'}),
    }),
  );
  const toastArg = vi.mocked(deps.setToast).mock.calls[0][0] as {
    action: {onClick: () => void};
  };
  toastArg.action.onClick();

  expect(deps.clearSessionState).toHaveBeenCalledOnce();
  expect(deps.setMessages).toHaveBeenCalledWith([]);
  expect(deps.setError).toHaveBeenCalledWith(null);
  expect(deps.setToast).toHaveBeenCalledWith(null);
  expect(deps.setInput).toHaveBeenCalledWith('Copy me');
  expect(deps.focusComposer).toHaveBeenCalledOnce();
});

test('handleEditMessage loads the message into the composer and focuses it', () => {
  const deps = makeDeps();
  const handlers = buildChatHandlers(deps);

  handlers.handleEditMessage(makeMessage({content: 'Original prompt'}));

  expect(deps.setInput).toHaveBeenCalledWith('Original prompt');
  expect(deps.focusComposer).toHaveBeenCalledOnce();
});

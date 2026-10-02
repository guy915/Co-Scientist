import {beforeEach, expect, test, vi} from 'vitest';
import {editInterviewTurn, retryInterviewTurn} from '@/api/runs';
import {buildChatHandlers} from './chat_session_handlers';
import {makeDeps, makeInterview} from './chat_session_handlers_test_support';
import {type ChatEntry} from '../pages/chat_timeline_bubble';
import {makeMessage} from '@/test_fixtures';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {
    ...actual,
    createInterview: vi.fn(),
    addInterviewTurn: vi.fn(),
    editInterviewTurn: vi.fn(),
    retryInterviewTurn: vi.fn(),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

// The messages updater a handler passed to setMessages, applied to `prev`.
function applyMessagesUpdate(
  setMessages: unknown,
  prev: ChatEntry[],
): ChatEntry[] {
  const updater = vi.mocked(setMessages as (value: unknown) => void).mock
    .calls[0][0] as unknown as (current: ChatEntry[]) => ChatEntry[];
  return updater(prev);
}

test('handleRetryMessage asks the Agent to answer that turn again', () => {
  const deps = makeDeps({interview: makeInterview()});
  const handlers = buildChatHandlers(deps);
  const answer = makeMessage({
    id: 'm2',
    role: 'assistant',
    content: 'Reply text',
    turnId: 7,
  });

  handlers.handleRetryMessage(answer);

  expect(retryInterviewTurn).toHaveBeenCalledWith(
    'interview-1',
    7,
    expect.objectContaining({
      onReasoning: expect.any(Function),
      onProse: expect.any(Function),
    }),
    expect.any(AbortSignal),
  );
  // The rejected answer leaves the transcript rather than being duplicated
  // below itself, which is what "retry" appeared to do before.
  expect(applyMessagesUpdate(deps.setMessages, [answer])).toEqual([]);
});

test('handleRetryMessage does nothing without a durable turn', () => {
  const deps = makeDeps({interview: makeInterview()});
  const handlers = buildChatHandlers(deps);

  handlers.handleRetryMessage(makeMessage({role: 'assistant'}));

  expect(retryInterviewTurn).not.toHaveBeenCalled();
  expect(deps.setMessages).not.toHaveBeenCalled();
});

test('handleCopyRequest copies the prompt and toasts a new chat', async () => {
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

test('handleEditMessage replaces the turn in place', () => {
  const deps = makeDeps({interview: makeInterview()});
  const handlers = buildChatHandlers(deps);
  const prompt = makeMessage({content: 'Original prompt', turnId: 3});
  const answer = makeMessage({id: 'm2', role: 'assistant', turnId: 4});

  handlers.handleEditMessage(prompt, '  Revised prompt  ');

  expect(editInterviewTurn).toHaveBeenCalledWith(
    'interview-1',
    3,
    'Revised prompt',
    expect.objectContaining({
      onReasoning: expect.any(Function),
      onProse: expect.any(Function),
    }),
    expect.any(AbortSignal),
  );
  // The edited prompt stays where it was and the answer derived from the old
  // wording goes; the composer is left alone for the next thing to say.
  expect(applyMessagesUpdate(deps.setMessages, [prompt, answer])).toEqual([
    {...prompt, content: 'Revised prompt'},
  ]);
  expect(deps.setInput).not.toHaveBeenCalled();
});

test('handleEditMessage ignores an empty revision', () => {
  const deps = makeDeps({interview: makeInterview()});
  const handlers = buildChatHandlers(deps);

  handlers.handleEditMessage(makeMessage({turnId: 3}), '   ');

  expect(editInterviewTurn).not.toHaveBeenCalled();
  expect(deps.setMessages).not.toHaveBeenCalled();
});

test('revisions are closed once a run has started', () => {
  // The timeline hides edit/retry affordances from the moment a run starts;
  // the handlers enforce the same state so no path rewinds the interview a
  // started run was created from.
  const deps = makeDeps({
    interview: makeInterview(),
    startedSession: {id: 'run-1', title: 'Started', at: 1},
  });
  const handlers = buildChatHandlers(deps);

  handlers.handleRetryMessage(makeMessage({role: 'assistant', turnId: 7}));
  handlers.handleEditMessage(makeMessage({turnId: 3}), 'Revised prompt');

  expect(retryInterviewTurn).not.toHaveBeenCalled();
  expect(editInterviewTurn).not.toHaveBeenCalled();
  expect(deps.setMessages).not.toHaveBeenCalled();
});

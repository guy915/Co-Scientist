import {beforeEach, expect, test, vi} from 'vitest';
import {
  addInterviewTurn,
  createInterview,
  editInterviewTurn,
  getInterview,
} from '@/api/runs';
import {buildChatHandlers} from './chat_session_handlers';
import {makeDeps, makeInterview} from './chat_session_handlers_test_support';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {
    ...actual,
    createInterview: vi.fn(),
    addInterviewTurn: vi.fn(),
    editInterviewTurn: vi.fn(),
    getInterview: vi.fn(),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

function abortError(): DOMException {
  return new DOMException('The user aborted a request.', 'AbortError');
}

test('handleStop aborts the turn currently in flight', async () => {
  const deps = makeDeps({
    interview: makeInterview(),
    input: 'one more thing',
  });
  vi.mocked(addInterviewTurn).mockImplementation(
    (_id, _content, _sinks, _docs, signal) =>
      new Promise((_resolve, reject) => {
        signal?.addEventListener('abort', () => reject(abortError()));
      }),
  );
  vi.mocked(getInterview).mockResolvedValue(makeInterview());
  const handlers = buildChatHandlers(deps);

  const submitted = handlers.handleSubmit({preventDefault: vi.fn()} as never);
  // Let submitComposerMessage reach its await before stopping it.
  await Promise.resolve();
  await Promise.resolve();
  handlers.handleStop();
  await submitted;

  expect(addInterviewTurn).toHaveBeenCalledOnce();
  const signal = vi.mocked(addInterviewTurn).mock.calls[0][4];
  expect(signal?.aborted).toBe(true);
});

test('a stopped turn on an existing interview resyncs, not errors', async () => {
  const interview = makeInterview();
  const resynced = makeInterview({
    turns: [
      ...interview.turns,
      {
        id: 2,
        role: 'user',
        content: 'one more thing',
        reasoning: null,
        fallback: false,
        created_at: 3,
      },
    ],
  });
  vi.mocked(addInterviewTurn).mockRejectedValue(abortError());
  vi.mocked(getInterview).mockResolvedValue(resynced);
  const deps = makeDeps({input: 'one more thing', interview});
  const handlers = buildChatHandlers(deps);

  await handlers.handleSubmit({preventDefault: vi.fn()} as never);

  // No error banner for a stop the scientist asked for.
  expect(deps.setError).not.toHaveBeenCalledWith(expect.any(String));
  // The server is now the sole source of truth for what got persisted.
  expect(getInterview).toHaveBeenCalledWith(interview.id);
  expect(deps.setInterview).toHaveBeenCalledWith(resynced);
  // The unfinished streamed draft never persisted; keeping it on screen
  // would vanish on reload, so it is dropped.
  expect(deps.setAgentDraft).toHaveBeenLastCalledWith('');
  expect(deps.setAgentReasoning).toHaveBeenLastCalledWith('');
});

test('a stopped fresh interview restores the composer and refreshes history', async () => {
  vi.mocked(createInterview).mockRejectedValue(abortError());
  const deps = makeDeps({input: 'Study liver fibrosis', interview: null});
  const handlers = buildChatHandlers(deps);

  await handlers.handleSubmit({preventDefault: vi.fn()} as never);

  // The interview id only arrives with the closing frame, so a stopped
  // creation leaves nothing to resync against.
  expect(getInterview).not.toHaveBeenCalled();
  expect(deps.setError).not.toHaveBeenCalledWith(expect.any(String));
  expect(deps.clearSessionState).toHaveBeenCalledOnce();
  expect(deps.setInput).toHaveBeenCalledWith('Study liver fibrosis');
  expect(deps.reloadHistory).toHaveBeenCalledOnce();
});

test('a real failure still shows the error banner, not a silent stop', async () => {
  vi.mocked(addInterviewTurn).mockRejectedValue(new Error('provider down'));
  const deps = makeDeps({input: 'one more thing', interview: makeInterview()});
  const handlers = buildChatHandlers(deps);

  await handlers.handleSubmit({preventDefault: vi.fn()} as never);

  expect(deps.setError).toHaveBeenCalledWith('provider down');
  expect(getInterview).not.toHaveBeenCalled();
});

test('a stopped revision resyncs the interview from the server', async () => {
  const interview = makeInterview();
  const resynced = makeInterview({status: 'active'});
  vi.mocked(editInterviewTurn).mockRejectedValue(abortError());
  vi.mocked(getInterview).mockResolvedValue(resynced);
  const deps = makeDeps({interview});
  const handlers = buildChatHandlers(deps);

  handlers.handleEditMessage(
    {
      id: 'm1',
      role: 'user',
      content: 'Original prompt',
      turnId: 3,
      created_at: 1,
    },
    'Revised prompt',
  );
  await Promise.resolve();
  await Promise.resolve();

  expect(deps.setError).not.toHaveBeenCalledWith(expect.any(String));
  expect(getInterview).toHaveBeenCalledWith(interview.id);
  expect(deps.setInterview).toHaveBeenCalledWith(resynced);
});

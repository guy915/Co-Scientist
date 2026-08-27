import {beforeEach, expect, test, vi} from 'vitest';
import {addInterviewTurn, askRunQuestion, createInterview} from '@/api/runs';
import {buildChatHandlers} from './chat_session_handlers';
import {makeDeps} from './chat_session_handlers_test_support';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {
    ...actual,
    createInterview: vi.fn(),
    addInterviewTurn: vi.fn(),
    askRunQuestion: vi.fn(),
  };
});

const STARTED = {id: 'run-1', title: 'A run', at: 1};

beforeEach(() => {
  vi.clearAllMocks();
});

function abortError(): DOMException {
  return new DOMException('The user aborted a request.', 'AbortError');
}

test('once a run has started, submit asks it a question instead of the interview', async () => {
  vi.mocked(askRunQuestion).mockImplementation(async (_id, _q, sinks) => {
    const s = sinks!;
    s.onSources?.([]);
    s.onChunk?.('Because ');
    s.onChunk?.('the evidence supports it.');
    return 7;
  });
  const deps = makeDeps({
    input: 'Why does this matter?',
    startedSession: STARTED,
  });
  const handlers = buildChatHandlers(deps);

  await handlers.handleSubmit({preventDefault: vi.fn()} as never);

  expect(askRunQuestion).toHaveBeenCalledWith(
    'run-1',
    'Why does this matter?',
    expect.objectContaining({
      onSources: expect.any(Function),
      onChunk: expect.any(Function),
    }),
    expect.any(Object),
  );
  // The A17 trap: never posts to the interview once a run has started.
  expect(addInterviewTurn).not.toHaveBeenCalled();
  expect(createInterview).not.toHaveBeenCalled();

  // Both the question and the streamed-then-finished answer land in the
  // timeline, in order.
  expect(deps.setMessages).toHaveBeenCalledTimes(2);
  const firstUpdater = vi.mocked(deps.setMessages).mock.calls[0][0] as (
    prev: unknown[],
  ) => {role: string; content: string}[];
  expect(firstUpdater([])).toEqual([
    expect.objectContaining({role: 'user', content: 'Why does this matter?'}),
  ]);
  const secondUpdater = vi.mocked(deps.setMessages).mock.calls[1][0] as (
    prev: unknown[],
  ) => {role: string; content: string}[];
  expect(secondUpdater([])).toEqual([
    expect.objectContaining({
      role: 'assistant',
      content: 'Because the evidence supports it.',
    }),
  ]);
});

test('without a started run, submit still advances the interview as before', async () => {
  vi.mocked(createInterview).mockResolvedValue({
    id: 'interview-1',
    client_id: 'client-1',
    status: 'active',
    fields: {
      research_challenge: 'g',
      focus_area: [],
      preferences: [],
      title: null,
    },
    current_question: 'q',
    documents: [],
    turns: [],
    created_at: 1,
    updated_at: 1,
    completed_at: null,
  });
  const deps = makeDeps({input: 'Study liver fibrosis', startedSession: null});
  const handlers = buildChatHandlers(deps);

  await handlers.handleSubmit({preventDefault: vi.fn()} as never);

  expect(createInterview).toHaveBeenCalledOnce();
  expect(askRunQuestion).not.toHaveBeenCalled();
});

test('stopping a Q&A turn drops the partial answer without an error banner', async () => {
  vi.mocked(askRunQuestion).mockImplementation(
    (_id, _q, sinks, signal) =>
      new Promise((_resolve, reject) => {
        sinks?.onChunk?.('partial');
        signal?.addEventListener('abort', () => reject(abortError()));
      }),
  );
  const deps = makeDeps({input: 'Why?', startedSession: STARTED});
  const handlers = buildChatHandlers(deps);

  const submitted = handlers.handleSubmit({preventDefault: vi.fn()} as never);
  await Promise.resolve();
  await Promise.resolve();
  handlers.handleStop();
  await submitted;

  expect(deps.setError).not.toHaveBeenCalledWith(expect.any(String));
  // Only the optimistic question bubble was appended -- the streamed
  // answer never persisted server-side, so nothing is added for it.
  expect(deps.setMessages).toHaveBeenCalledTimes(1);
  expect(deps.setAgentDraft).toHaveBeenLastCalledWith('');
});

test('a real failure asking the run shows the error banner', async () => {
  vi.mocked(askRunQuestion).mockRejectedValue(new Error('provider down'));
  const deps = makeDeps({input: 'Why?', startedSession: STARTED});
  const handlers = buildChatHandlers(deps);

  await handlers.handleSubmit({preventDefault: vi.fn()} as never);

  expect(deps.setError).toHaveBeenCalledWith('provider down');
});

test('marks the turn busy for the round trip, same as an interview turn', async () => {
  // Composer's `busy` prop (fed by isStarting) is what blocks a second
  // Enter/Send while a turn is in flight -- without this a question asked
  // mid-stream would orphan the first turn's AbortController and interleave
  // both answers into the one shared draft.
  let resolveAsk: (id: number) => void = () => {};
  vi.mocked(askRunQuestion).mockImplementation(
    () => new Promise(resolve => (resolveAsk = resolve)),
  );
  const deps = makeDeps({input: 'Why?', startedSession: STARTED});
  const handlers = buildChatHandlers(deps);

  const submitted = handlers.handleSubmit({preventDefault: vi.fn()} as never);
  await Promise.resolve();
  expect(deps.setIsStarting).toHaveBeenLastCalledWith(true);

  resolveAsk(1);
  await submitted;
  expect(deps.setIsStarting).toHaveBeenLastCalledWith(false);
});

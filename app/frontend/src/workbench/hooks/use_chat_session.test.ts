import {
  type FormEvent,
  createElement,
  Suspense,
  startTransition,
  useLayoutEffect,
} from 'react';
import {act, render, renderHook} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {useChatSession} from './use_chat_session';
import {type ChatEntry} from '../pages/chat_timeline_bubble';
import * as clientId from '@/lib/client_id';
import {makeMessage, makeSpec} from '@/test_fixtures';

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    createInterview: vi.fn(),
    addInterviewTurn: vi.fn(),
    askRunQuestion: vi.fn(),
    createRun: vi.fn(),
    startRun: vi.fn(),
    stageDocument: vi.fn(),
    editInterviewTurn: vi.fn(),
    retryInterviewTurn: vi.fn(),
  };
});

function completedInterview(goal: string) {
  return {
    id: 'interview-1',
    client_id: 'client-1',
    status: 'completed' as const,
    fields: {
      research_challenge: goal,
      focus_area: ['Hepatic stellate cells'],
      preferences: ['Prioritize mechanistic novelty'],
      title: 'Liver fibrosis',
    },
    current_question: null,
    documents: [],
    turns: [
      {
        id: 1,
        role: 'user' as const,
        content: goal,
        reasoning: null,
        fallback: false,
        questions: [],
        created_at: 1,
      },
      {
        id: 2,
        role: 'agent' as const,
        content: 'The goal is ready.',
        reasoning: null,
        fallback: false,
        questions: [],
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: 2,
  };
}

const submitEvent = () =>
  ({preventDefault: () => undefined}) as unknown as FormEvent<HTMLFormElement>;

function makeDeps() {
  return {
    reloadHistory: vi.fn().mockResolvedValue(undefined),
    focusComposer: vi.fn(),
    onChatStarted: vi.fn(),
    setToast: vi.fn(),
    pubmedEnabled: true,
    webSearchEnabled: true,
  };
}

function renderSession(deps = makeDeps()) {
  const hook = renderHook(() => useChatSession(deps));
  return {...hook, deps};
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(runsApi.createInterview).mockImplementation(async goal =>
    completedInterview(goal),
  );
});

it('starts empty with no conversation', () => {
  const {result} = renderSession();
  expect(result.current.hasConversation).toBe(false);
  expect(result.current.draft).toBeNull();
  expect(result.current.messages).toHaveLength(0);
});

it('submitting a goal stages a draft spec and logs it', async () => {
  const {result} = renderSession();

  act(() => result.current.setInput('How is liver fibrosis reversed?'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });

  expect(result.current.draft).not.toBeNull();
  expect(result.current.hasConversation).toBe(true);
  expect(result.current.messages.filter(m => m.role === 'user')).toHaveLength(
    1,
  );
  expect(result.current.input).toBe('');
});

it('ignores a whitespace-only submission', async () => {
  const {result} = renderSession();
  act(() => result.current.setInput('   '));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });
  expect(result.current.draft).toBeNull();
  expect(result.current.messages).toHaveLength(0);
});

it('a completed interview leaves its persisted draft stable', async () => {
  const {result} = renderSession();

  act(() => result.current.setInput('Study MASLD fibrosis'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });
  const afterFirst = result.current.messages.length;

  expect(result.current.draft).not.toBeNull();
  expect(result.current.messages.length).toBe(afterFirst);
});

it('cancelling clears the session and shows a toast', async () => {
  const {result, deps} = renderSession();

  act(() => result.current.setInput('Study something'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });

  act(() => result.current.handleCancelDraftSpec());

  expect(result.current.draft).toBeNull();
  expect(result.current.messages).toHaveLength(0);
  expect(result.current.hasConversation).toBe(false);
  expect(deps.setToast).toHaveBeenCalledWith('The session was canceled');
});

it('resetSession clears all state', async () => {
  const {result} = renderSession();
  act(() => result.current.setInput('Study something'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });

  act(() => result.current.resetSession());

  expect(result.current.hasConversation).toBe(false);
  expect(result.current.input).toBe('');
  expect(result.current.messages).toHaveLength(0);
});

it('editing a message revises it in place, not via the composer', async () => {
  vi.mocked(runsApi.editInterviewTurn).mockResolvedValue(
    completedInterview('Revised prompt'),
  );
  const {result} = renderSession();
  act(() => result.current.setInput('Original prompt'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });
  const [prompt] = result.current.messages as ChatEntry[];

  await act(async () => {
    result.current.handleEditMessage(prompt, 'Revised prompt');
    await Promise.resolve();
  });

  expect(runsApi.editInterviewTurn).toHaveBeenCalledWith(
    'interview-1',
    prompt.turnId,
    'Revised prompt',
    expect.objectContaining({
      onReasoning: expect.any(Function),
      onProse: expect.any(Function),
    }),
    expect.any(AbortSignal),
  );
  expect(result.current.messages).toHaveLength(1);
  expect(result.current.messages[0].content).toBe('Revised prompt');
  expect(result.current.input).toBe('');
});

it('starting a run creates it and reloads history', async () => {
  vi.mocked(runsApi.createRun).mockResolvedValue({
    id: 'run-xyz',
    status: 'draft',
  } as Awaited<ReturnType<typeof runsApi.createRun>>);
  vi.mocked(runsApi.startRun).mockResolvedValue({
    id: 'run-xyz',
    status: 'running',
  });
  const {result, deps} = renderSession();

  act(() => result.current.setInput('Study liver fibrosis'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });
  await act(async () => {
    await result.current.handleStartRun();
  });

  expect(runsApi.createRun).toHaveBeenCalledOnce();
  expect(runsApi.startRun).toHaveBeenCalledWith('run-xyz');
  expect(result.current.startedSession?.id).toBe('run-xyz');
  expect(result.current.draft).toBeNull();
  expect(deps.reloadHistory).toHaveBeenCalled();
});

it('asks the run instead of posting further interview turns once started', async () => {
  vi.mocked(runsApi.createRun).mockResolvedValue({
    id: 'run-xyz',
    status: 'draft',
  } as Awaited<ReturnType<typeof runsApi.createRun>>);
  vi.mocked(runsApi.startRun).mockResolvedValue({
    id: 'run-xyz',
    status: 'running',
  });
  vi.mocked(runsApi.askRunQuestion).mockResolvedValue(9);
  const {result} = renderSession();

  act(() => result.current.setInput('Study liver fibrosis'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });
  await act(async () => {
    await result.current.handleStartRun();
  });
  expect(result.current.startedSession?.id).toBe('run-xyz');
  expect(result.current.input).toBe('');
  const messagesAfterStart = result.current.messages.length;

  act(() => result.current.setInput('one more thing'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });

  expect(runsApi.addInterviewTurn).not.toHaveBeenCalled();
  expect(runsApi.createInterview).toHaveBeenCalledOnce();
  expect(runsApi.askRunQuestion).toHaveBeenCalledWith(
    'run-xyz',
    'one more thing',
    expect.any(Object),
    expect.any(AbortSignal),
  );
  expect(result.current.messages).toHaveLength(messagesAfterStart + 2);
});

it('resetting a started session reopens the composer for a new chat', async () => {
  vi.mocked(runsApi.createRun).mockResolvedValue({
    id: 'run-xyz',
    status: 'draft',
  } as Awaited<ReturnType<typeof runsApi.createRun>>);
  vi.mocked(runsApi.startRun).mockResolvedValue({
    id: 'run-xyz',
    status: 'running',
  });
  const {result} = renderSession();

  act(() => result.current.setInput('Study liver fibrosis'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });
  await act(async () => {
    await result.current.handleStartRun();
  });
  expect(result.current.startedSession).not.toBeNull();

  act(() => result.current.resetSession());
  act(() => result.current.setInput('A brand new goal'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent());
  });

  expect(runsApi.createInterview).toHaveBeenCalledTimes(2);
  expect(runsApi.createInterview).toHaveBeenLastCalledWith(
    'A brand new goal',
    expect.objectContaining({
      onReasoning: expect.any(Function),
      onProse: expect.any(Function),
    }),
    [],
    expect.any(AbortSignal),
  );
});

it('stages attached documents before the run is created', async () => {
  const file = new File(['private result'], 'result.txt', {
    type: 'text/plain',
  });
  vi.mocked(runsApi.createRun).mockResolvedValue({
    id: 'run-with-file',
    status: 'draft',
  } as Awaited<ReturnType<typeof runsApi.createRun>>);
  vi.mocked(runsApi.stageDocument).mockResolvedValue({
    id: 'doc-1',
    title: 'result.txt',
    sha256: 'abc',
    byte_size: 14,
    mime_type: 'text/plain',
    extraction_tool: 'text',
  });
  vi.mocked(runsApi.startRun).mockResolvedValue({
    id: 'run-with-file',
    status: 'running',
  });
  const {result} = renderSession();

  act(() => result.current.setInput('Use my private result'));
  await act(async () => {
    await result.current.handleSubmit(submitEvent(), [file]);
  });

  expect(runsApi.stageDocument).toHaveBeenCalledWith(file);
  expect(runsApi.createInterview).toHaveBeenCalledWith(
    'Use my private result',
    expect.objectContaining({
      onReasoning: expect.any(Function),
      onProse: expect.any(Function),
    }),
    ['doc-1'],
    expect.any(AbortSignal),
  );

  await act(async () => {
    await result.current.handleStartRun();
  });

  expect(vi.mocked(runsApi.createRun).mock.calls[0][0].document_ids).toEqual([
    'doc-1',
  ]);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => {
    resolve = done;
  });
  return {promise, resolve};
}

it('queues functional public setters against the current state and preserves no-op card identity', () => {
  const {result} = renderSession();
  const first = makeMessage({id: 'first', content: 'first'});
  const second = makeMessage({id: 'second', content: 'second'});
  const setMessages = result.current.setMessages;
  act(() => {
    result.current.setInput('draft');
    result.current.setInput(current => current + ' text');
    result.current.setMessages(current => [...current, first]);
    result.current.setMessages(current => [...current, second]);
    result.current.setStartedSession({id: 'run-1', title: 'A run', at: 1});
    result.current.setStartedSession(
      current => current && {...current, intro: (current.intro ?? '') + 'One'},
    );
    result.current.setStartedSession(
      current => current && {...current, intro: (current.intro ?? '') + ' two'},
    );
  });
  expect(result.current.input).toBe('draft text');
  expect(result.current.messages).toEqual([first, second]);
  expect(result.current.startedSession?.intro).toBe('One two');
  expect(result.current.setMessages).toBe(setMessages);
  const card = result.current.startedSession;
  act(() => result.current.setStartedSession(current => current));
  expect(result.current.startedSession).toBe(card);
});

it('accumulates streamed fragments before settling and keeps optimistic IDs outside StrictMode replay', async () => {
  const response = deferred<ReturnType<typeof completedInterview>>();
  vi.mocked(runsApi.createInterview).mockImplementation((_text, sinks) => {
    sinks?.onReasoning?.('first ');
    sinks?.onReasoning?.('second');
    sinks?.onProse?.('one ');
    sinks?.onProse?.('two');
    return response.promise;
  });
  const idSpy = vi.spyOn(clientId, 'makePrefixedId');
  const {result} = renderHook(() => useChatSession(makeDeps()), {
    reactStrictMode: true,
  });
  act(() => result.current.setInput('Study fibrosis'));
  let submitted!: Promise<void>;
  await act(async () => {
    submitted = result.current.handleSubmit(submitEvent());
    await Promise.resolve();
  });
  expect(result.current.agentReasoning).toBe('first second');
  expect(result.current.agentDraft).toBe('one two');
  expect(result.current.messages).toHaveLength(1);
  expect(idSpy).toHaveBeenCalledTimes(1);
  const optimisticId = result.current.messages[0].id;
  expect(optimisticId).toMatch(/^user-/);
  await act(async () => {
    response.resolve(completedInterview('Study fibrosis'));
    await submitted;
  });
  expect(result.current.agentDraft).toBe('');
  expect(result.current.agentReasoning).toBe('');
  expect(result.current.messages[0].id).toBe('turn-1');
  idSpy.mockRestore();
});

it('stages a complete closing value and samples its default clock before replay', () => {
  const {result} = renderHook(() => useChatSession(makeDeps()), {
    reactStrictMode: true,
  });
  const now = vi.spyOn(Date, 'now').mockReturnValue(12500);
  const spec = makeSpec();
  act(() =>
    result.current.stageDraftSpec(spec, undefined, {
      message: 'Scope ready',
      reasoning: 'Complete',
      turnId: 7,
      fallback: true,
    }),
  );
  expect(result.current.draft).toEqual({
    spec,
    createdAt: 12.5,
    intro: 'Scope ready',
    reasoning: 'Complete',
    turnId: 7,
    fallback: true,
  });
  expect(now).toHaveBeenCalledTimes(1);
  expect(result.current.confirmed).toBeNull();
  expect(result.current.startedSession).toBeNull();
  now.mockRestore();
});

it('keeps an in-flight service snapshot while stable handlers adopt later committed services', async () => {
  const response = deferred<ReturnType<typeof completedInterview>>();
  vi.mocked(runsApi.createInterview).mockReturnValueOnce(response.promise);
  const original = makeDeps();
  const next = makeDeps();
  const {result, rerender} = renderHook(({view}) => useChatSession(view), {
    initialProps: {view: original},
  });
  const submit = result.current.handleSubmit;
  act(() => result.current.setInput('Original goal'));
  let pending!: Promise<void>;
  act(() => {
    pending = submit(submitEvent());
  });
  rerender({view: next});
  await act(async () => {
    response.resolve(completedInterview('Original goal'));
    await pending;
  });
  expect(original.onChatStarted).toHaveBeenCalledWith('interview-1');
  expect(next.onChatStarted).not.toHaveBeenCalled();
  act(() => {
    result.current.resetSession();
    result.current.setInput('Next goal');
  });
  await act(async () => {
    await submit(submitEvent());
  });
  expect(next.onChatStarted).toHaveBeenCalledWith('interview-1');
  expect(runsApi.createInterview).toHaveBeenLastCalledWith(
    'Next goal',
    expect.any(Object),
    [],
    expect.any(AbortSignal),
  );
  expect(result.current.handleSubmit).toBe(submit);
});

it('does not publish input or mutated services from a suspended render to committed handlers', async () => {
  const original = makeDeps();
  const committedToast = original.setToast;
  const suspendedToast = vi.fn();
  const suspended = new Promise<void>(() => {});
  let committed!: ReturnType<typeof useChatSession>;
  function Harness({blocked}: {blocked: boolean}) {
    const session = useChatSession(original);
    useLayoutEffect(() => {
      committed = session;
    });
    if (blocked) throw suspended;
    return createElement('span', null, 'committed');
  }
  const element = (blocked: boolean) =>
    createElement(
      Suspense,
      {fallback: 'loading'},
      createElement(Harness, {blocked}),
    );
  const {rerender} = render(element(false));
  act(() => committed.setInput('Committed goal'));
  const submit = committed.handleSubmit;
  original.setToast = suspendedToast;
  act(() => {
    startTransition(() => {
      committed.setInput('Uncommitted goal');
      rerender(element(true));
    });
  });
  await act(async () => {
    await submit(submitEvent());
  });
  expect(runsApi.createInterview).toHaveBeenCalledWith(
    'Committed goal',
    expect.any(Object),
    [],
    expect.any(AbortSignal),
  );
  expect(committedToast).toHaveBeenCalledWith(null);
  expect(suspendedToast).not.toHaveBeenCalled();
});

it('reset aborts synchronously and clears the current view before request settlement', async () => {
  let signal: AbortSignal | undefined;
  vi.mocked(runsApi.createInterview).mockImplementation(
    (_text, _sinks, _docs, currentSignal) =>
      new Promise((_resolve, reject) => {
        signal = currentSignal;
        signal?.addEventListener('abort', () =>
          reject(new DOMException('Stopped', 'AbortError')),
        );
      }),
  );
  const {result} = renderSession();
  act(() => result.current.setInput('Abandoned goal'));
  let pending!: Promise<void>;
  await act(async () => {
    pending = result.current.handleSubmit(submitEvent());
    await Promise.resolve();
  });
  act(() => result.current.resetSession());
  expect(signal?.aborted).toBe(true);
  expect(result.current.hasConversation).toBe(false);
  expect(result.current.input).toBe('');
  expect(result.current.isStarting).toBe(false);
  await act(async () => {
    await pending;
  });
});

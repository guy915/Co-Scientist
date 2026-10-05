import {makeRunMessage} from '@/test_fixtures';
import {expect, test, vi, beforeEach, describe} from 'vitest';
import {buildChatHandlers} from './chat_session_handlers';
import {
  addInterviewTurn,
  askRunQuestion,
  createInterview,
  retryInterviewTurn,
  editInterviewTurn,
  getInterview,
  getRunMessages,
  type Interview,
} from '@/api/runs';
import {makeSpec, makeMessage} from '@/test_fixtures';
import type {SessionState} from './use_chat_session';
import {sessionRuntime} from './__tests__/session_helpers';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {
    ...actual,
    createInterview: vi.fn(),
    addInterviewTurn: vi.fn(),
    askRunQuestion: vi.fn(),
    editInterviewTurn: vi.fn(),
    retryInterviewTurn: vi.fn(),
    getInterview: vi.fn(),
    getRunMessages: vi.fn(),
  };
});
beforeEach(() => vi.resetAllMocks());

describe('chat session handlers', () => {
  test('starts a model-driven interview with no local draft', async () => {
    const interview = makeInterview();
    vi.mocked(createInterview).mockResolvedValue(interview);
    const deps = makeDeps({input: 'Study liver fibrosis'});
    const handlers = buildChatHandlers(deps);

    await handlers.handleSubmit({preventDefault: vi.fn()} as never);

    expect(createInterview).toHaveBeenCalledWith(
      'Study liver fibrosis',
      expect.objectContaining({
        onReasoning: expect.any(Function),
        onProse: expect.any(Function),
      }),
      [],
      expect.any(AbortSignal),
    );
    expect(deps.state.interview).toEqual(interview);
    expect(deps.state.draft).toBeNull();
    expect(deps.observed.some(state => state.messages.length === 1)).toBe(true);
  });

  test('asks the run a question instead of posting to the closed interview', async () => {
    // Starting closes the interview server-side; later turns must use run Q&A.
    vi.clearAllMocks();
    vi.mocked(askRunQuestion).mockResolvedValue(1);
    const deps = makeDeps({
      input: 'one more thing',
      interview: makeInterview({status: 'completed'}),
      startedSession: {id: 'run-1', title: 'Started', at: 1},
    });

    await buildChatHandlers(deps).handleSubmit({
      preventDefault: vi.fn(),
    } as never);

    expect(addInterviewTurn).not.toHaveBeenCalled();
    expect(createInterview).not.toHaveBeenCalled();
    expect(askRunQuestion).toHaveBeenCalledWith(
      'run-1',
      'one more thing',
      expect.any(Object),
      expect.any(AbortSignal),
    );
    expect(deps.state.input).toBe('');
  });

  test('stages only a completed persisted interview derivation', async () => {
    const active = makeInterview();
    const completed = makeInterview({
      status: 'completed',
      fields: {
        research_challenge: 'Study liver fibrosis',
        focus_area: ['Stellate-cell metabolism'],
        preferences: ['Human evidence'],
        title: 'Fibrosis metabolism',
      },
    });
    vi.mocked(addInterviewTurn).mockResolvedValue(completed);
    const deps = makeDeps({input: 'Focus on metabolism', interview: active});

    await buildChatHandlers(deps).handleSubmit({
      preventDefault: vi.fn(),
    } as never);

    expect(addInterviewTurn).toHaveBeenCalledWith(
      active.id,
      'Focus on metabolism',
      expect.objectContaining({
        onReasoning: expect.any(Function),
        onProse: expect.any(Function),
      }),
      [],
      expect.any(AbortSignal),
    );
    expect(deps.state.draft).toMatchObject({
      spec: {
        interviewId: active.id,
        goal: 'Study liver fibrosis',
        attributes: ['Stellate-cell metabolism'],
        requirements: ['Human evidence'],
      },
      createdAt: 2,
      intro: 'Which mechanisms should I prioritize?',
      turnId: 1,
    });
    expect(deps.state.draft?.reasoning).toBeUndefined();
    expect(deps.observed.some(state => state.messages.length === 1)).toBe(true);
  });

  test('drops the streamed reply once the turn it belonged to resolves', async () => {
    // Stale live drafts would reappear whenever another operation awaits the
    // Agent.
    vi.clearAllMocks();
    vi.mocked(createInterview).mockImplementation(async (_text, sinks) => {
      sinks?.onReasoning?.('Ask about the model system.');
      sinks?.onProse?.('Which model system should this be built around?');
      return makeInterview();
    });
    const deps = makeDeps({input: 'Study liver fibrosis'});

    await buildChatHandlers(deps).handleSubmit({
      preventDefault: vi.fn(),
    } as never);

    expect(
      deps.observed.some(
        state =>
          state.agentDraft ===
          'Which model system should this be built around?',
      ),
    ).toBe(true);

    expect(deps.state.agentDraft).toBe('');
    expect(deps.state.agentReasoning).toBe('');
  });
});

describe('chat session handlers draft spec', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('handleRetryDraftSpec re-derives the plan from its own turn', () => {
    const spec = makeSpec({goal: 'Study X', focus: 'prefer_novelty'});
    const deps = makeDeps({
      interview: makeInterview(),
      draft: {spec, createdAt: 1, turnId: 9},
    });
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryDraftSpec();

    expect(retryInterviewTurn).toHaveBeenCalledWith(
      'interview-1',
      9,
      expect.objectContaining({
        onReasoning: expect.any(Function),
        onProse: expect.any(Function),
      }),
      expect.any(AbortSignal),
    );
    expect(deps.state.draft).toBeNull();
  });

  test('handleRetryDraftSpec is a no-op without a staged draft', () => {
    const deps = makeDeps({interview: makeInterview(), draft: null});
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryDraftSpec();

    expect(retryInterviewTurn).not.toHaveBeenCalled();
  });

  test('handleCancelDraftSpec resets state and shows a cancel toast', () => {
    const deps = makeDeps({draft: {spec: makeSpec(), createdAt: 1}});
    const handlers = buildChatHandlers(deps);

    handlers.handleCancelDraftSpec();

    expect(deps.state).toMatchObject({
      interview: null,
      draft: null,
      confirmed: null,
      startedSession: null,
    });
    expect(deps.services.setToast).toHaveBeenCalledWith(
      'The session was canceled',
    );
  });
});

describe('chat session handlers messages', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('handleRetryMessage asks the Agent to answer that turn again', () => {
    const deps = makeDeps({interview: makeInterview()});
    const handlers = buildChatHandlers(deps);
    const answer = makeMessage({
      id: 'm2',
      role: 'assistant',
      content: 'Reply text',
      turnId: 7,
    });

    deps.update({messages: [answer]});
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
    expect(deps.state.messages).toEqual([]);
  });

  test('handleRetryMessage does nothing without a durable turn', () => {
    const deps = makeDeps({interview: makeInterview()});
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryMessage(makeMessage({role: 'assistant'}));

    expect(retryInterviewTurn).not.toHaveBeenCalled();
    expect(deps.update).not.toHaveBeenCalled();
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
    expect(deps.services.setToast).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Prompt copied',
        action: expect.objectContaining({label: 'Start new chat'}),
      }),
    );
    const toastArg = vi.mocked(deps.services.setToast).mock.calls[0][0] as {
      action: {onClick: () => void};
    };
    toastArg.action.onClick();

    expect(deps.state).toMatchObject({
      interview: null,
      draft: null,
      confirmed: null,
      startedSession: null,
    });
    expect(deps.state.messages).toEqual([]);
    expect(deps.state.error).toBeNull();
    expect(deps.services.setToast).toHaveBeenCalledWith(null);
    expect(deps.state.input).toBe('Copy me');
    expect(deps.services.focusComposer).toHaveBeenCalledOnce();
  });

  test('handleEditMessage replaces the turn in place', () => {
    const deps = makeDeps({
      interview: makeInterview(),
      input: 'Unsent composer draft',
    });
    const handlers = buildChatHandlers(deps);
    const prompt = makeMessage({content: 'Original prompt', turnId: 3});
    const answer = makeMessage({id: 'm2', role: 'assistant', turnId: 4});

    deps.update({messages: [prompt, answer]});
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
    expect(deps.state.messages).toEqual([
      {...prompt, content: 'Revised prompt'},
    ]);
    expect(deps.state.input).toBe('Unsent composer draft');
  });

  test('handleEditMessage ignores an empty revision', () => {
    const deps = makeDeps({interview: makeInterview()});
    const handlers = buildChatHandlers(deps);

    handlers.handleEditMessage(makeMessage({turnId: 3}), '   ');

    expect(editInterviewTurn).not.toHaveBeenCalled();
    expect(deps.update).not.toHaveBeenCalled();
  });

  test('revisions are closed once a run has started', () => {
    const deps = makeDeps({
      interview: makeInterview(),
      startedSession: {id: 'run-1', title: 'Started', at: 1},
    });
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryMessage(makeMessage({role: 'assistant', turnId: 7}));
    handlers.handleEditMessage(makeMessage({turnId: 3}), 'Revised prompt');

    expect(retryInterviewTurn).not.toHaveBeenCalled();
    expect(editInterviewTurn).not.toHaveBeenCalled();
    expect(deps.update).not.toHaveBeenCalled();
  });
});

describe('chat session handlers qa', () => {
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
    expect(addInterviewTurn).not.toHaveBeenCalled();
    expect(createInterview).not.toHaveBeenCalled();

    expect(deps.observed.some(state => state.messages.length === 1)).toBe(true);
    expect(deps.state.messages).toEqual([
      expect.objectContaining({role: 'user', content: 'Why does this matter?'}),
      expect.objectContaining({
        role: 'assistant',
        content: 'Because the evidence supports it.',
      }),
    ]);
  });

  test('a Q&A turn relays reasoning live and persists it on the settled bubble', async () => {
    vi.mocked(askRunQuestion).mockImplementation(async (_id, _q, sinks) => {
      const s = sinks!;
      s.onReasoning?.('Checking the evidence first. ');
      s.onReasoning?.('It supports the claim.');
      s.onChunk?.('Yes, because of the evidence.');
      return 9;
    });
    const deps = makeDeps({
      input: 'Does the evidence support this?',
      startedSession: STARTED,
    });
    const handlers = buildChatHandlers(deps);

    await handlers.handleSubmit({preventDefault: vi.fn()} as never);

    expect(askRunQuestion).toHaveBeenCalledWith(
      'run-1',
      'Does the evidence support this?',
      expect.objectContaining({
        onSources: expect.any(Function),
        onReasoning: expect.any(Function),
        onChunk: expect.any(Function),
      }),
      expect.any(Object),
    );
    expect(
      deps.observed.some(
        state =>
          state.agentReasoning ===
          'Checking the evidence first. It supports the claim.',
      ),
    ).toBe(true);
    expect(deps.state.messages.at(-1)).toMatchObject({
      role: 'assistant',
      content: 'Yes, because of the evidence.',
      reasoning: 'Checking the evidence first. It supports the claim.',
    });
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
    const deps = makeDeps({
      input: 'Study liver fibrosis',
      startedSession: null,
    });
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

    expect(deps.state.error).toBeNull();
    expect(deps.state.messages).toHaveLength(1);
    expect(deps.state.agentDraft).toBe('');
  });

  test('a real failure asking the run shows the error banner', async () => {
    vi.mocked(askRunQuestion).mockRejectedValue(new Error('provider down'));
    const deps = makeDeps({input: 'Why?', startedSession: STARTED});
    const handlers = buildChatHandlers(deps);

    await handlers.handleSubmit({preventDefault: vi.fn()} as never);

    expect(deps.state.error).toBe('provider down');
  });

  test('marks the turn busy for the round trip, same as an interview turn', async () => {
    // Concurrent sends orphan AbortControllers and interleave replies into one
    // draft.
    let resolveAsk: (id: number) => void = () => {};
    vi.mocked(askRunQuestion).mockImplementation(
      () => new Promise(resolve => (resolveAsk = resolve)),
    );
    const deps = makeDeps({input: 'Why?', startedSession: STARTED});
    const handlers = buildChatHandlers(deps);

    const submitted = handlers.handleSubmit({preventDefault: vi.fn()} as never);
    await Promise.resolve();
    expect(deps.state.isStarting).toBe(true);

    resolveAsk(1);
    await submitted;
    expect(deps.state.isStarting).toBe(false);
  });
});

describe('chat session handlers stop', () => {
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
          questions: [],
          created_at: 3,
        },
      ],
    });
    vi.mocked(addInterviewTurn).mockRejectedValue(abortError());
    vi.mocked(getInterview).mockResolvedValue(resynced);
    const deps = makeDeps({input: 'one more thing', interview});
    const handlers = buildChatHandlers(deps);

    await handlers.handleSubmit({preventDefault: vi.fn()} as never);

    expect(deps.state.error).toBeNull();
    expect(getInterview).toHaveBeenCalledWith(interview.id);
    expect(deps.state.interview).toEqual(resynced);
    // Unpersisted interrupted prose must disappear so the live view matches
    // reload.
    expect(deps.state.agentDraft).toBe('');
    expect(deps.state.agentReasoning).toBe('');
  });

  test('a stopped fresh interview restores the composer and refreshes history', async () => {
    vi.mocked(createInterview).mockRejectedValue(abortError());
    const deps = makeDeps({input: 'Study liver fibrosis', interview: null});
    const handlers = buildChatHandlers(deps);

    await handlers.handleSubmit({preventDefault: vi.fn()} as never);

    // Stopped creation has no interview id until its closing frame arrives.
    expect(getInterview).not.toHaveBeenCalled();
    expect(deps.state.error).toBeNull();
    expect(deps.state).toMatchObject({
      interview: null,
      draft: null,
      confirmed: null,
      startedSession: null,
    });
    expect(deps.state.input).toBe('Study liver fibrosis');
    expect(deps.services.reloadHistory).toHaveBeenCalledOnce();
  });

  test('a real failure still shows the error banner, not a silent stop', async () => {
    vi.mocked(addInterviewTurn).mockRejectedValue(new Error('provider down'));
    const deps = makeDeps({
      input: 'one more thing',
      interview: makeInterview(),
    });
    const handlers = buildChatHandlers(deps);

    await handlers.handleSubmit({preventDefault: vi.fn()} as never);

    expect(deps.state.error).toBe('provider down');
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

    expect(deps.state.error).toBeNull();
    expect(getInterview).toHaveBeenCalledWith(interview.id);
    expect(deps.state.interview).toEqual(resynced);
  });
});

export function makeInterview(overrides: Partial<Interview> = {}): Interview {
  return {
    id: 'interview-1',
    client_id: 'client-1',
    status: 'active',
    fields: {
      research_challenge: 'Study liver fibrosis',
      focus_area: [],
      preferences: [],
      title: null,
    },
    current_question: 'Which mechanisms should I prioritize?',
    documents: [],
    turns: [
      {
        id: 1,
        role: 'agent',
        content: 'Which mechanisms should I prioritize?',
        reasoning: null,
        fallback: false,
        questions: [],
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: null,
    ...overrides,
  };
}

export function makeDeps(overrides: Partial<SessionState> = {}) {
  return sessionRuntime(overrides);
}

test('revises post-start Q&A and adopts durable replacement IDs', async () => {
  const deps = makeDeps({
    startedSession: {id: 'run-1', title: 'Research', at: 1},
  });
  vi.mocked(getRunMessages).mockResolvedValue([
    makeRunMessage({id: 9, content: 'Revised', created_at: 2}),
    makeRunMessage({
      id: 10,
      sender: 'system',
      content: 'Answer',
      created_at: 3,
    }),
  ]);
  buildChatHandlers(deps).handleEditMessage(
    makeMessage({messageId: 7}),
    'Revised',
  );
  await vi.waitFor(() => expect(deps.state.isAwaitingAgent).toBe(false));
  expect(askRunQuestion).toHaveBeenCalledWith(
    'run-1',
    'Revised',
    expect.any(Object),
    expect.any(AbortSignal),
    7,
  );
  expect(deps.state.messages.map(row => row.messageId)).toEqual([9, 10]);
  expect(editInterviewTurn).not.toHaveBeenCalled();
});

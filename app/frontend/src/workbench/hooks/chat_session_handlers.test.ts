import {describe, expect, it, vi} from 'vitest';
import {buildChatHandlers} from './chat_session_handlers';
import type {HandlerDeps} from './chat_session_types';
import type {ChatEntry} from '../pages/chat_timeline_cards';
import type {InferredRunSpec} from '../run_spec';
import {addInterviewTurn, createInterview, type Interview} from '@/api/runs';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {...actual, createInterview: vi.fn(), addInterviewTurn: vi.fn()};
});

function makeInterview(overrides: Partial<Interview> = {}): Interview {
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
    turns: [
      {
        id: 1,
        role: 'agent',
        content: 'Which mechanisms should I prioritize?',
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: null,
    ...overrides,
  };
}

function makeSpec(overrides: Partial<InferredRunSpec> = {}): InferredRunSpec {
  return {
    goal: 'Study liver fibrosis',
    requirements: ['Req A'],
    attributes: ['Attr A'],
    criteria: ['Crit A'],
    focus: 'balance',
    tier: 'standard',
    ...overrides,
  };
}

function makeMessage(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return {
    id: 'm1',
    role: 'user',
    content: 'Hello',
    created_at: 1,
    ...overrides,
  };
}

function makeDeps(overrides: Partial<HandlerDeps> = {}): HandlerDeps {
  return {
    input: '',
    interview: null,
    setInterview: vi.fn(),
    setInput: vi.fn(),
    draft: null,
    setDraft: vi.fn(),
    setConfirmed: vi.fn(),
    setStartedSession: vi.fn(),
    setIsStarting: vi.fn(),
    setMessages: vi.fn(),
    setError: vi.fn(),
    pendingAttachments: [],
    setPendingAttachments: vi.fn(),
    setToast: vi.fn(),
    clearSessionState: vi.fn(),
    stageDraftSpec: vi.fn(),
    focusComposer: vi.fn(),
    reloadHistory: vi.fn().mockResolvedValue(undefined),
    pubmedEnabled: true,
    ...overrides,
  };
}

describe('buildChatHandlers', () => {
  it('starts a model-driven interview without deriving a local draft', async () => {
    const interview = makeInterview();
    vi.mocked(createInterview).mockResolvedValue(interview);
    const deps = makeDeps({input: 'Study liver fibrosis'});
    const handlers = buildChatHandlers(deps);

    await handlers.handleSubmit({preventDefault: vi.fn()} as never);

    expect(createInterview).toHaveBeenCalledWith('Study liver fibrosis');
    expect(deps.setInterview).toHaveBeenCalledWith(interview);
    expect(deps.stageDraftSpec).not.toHaveBeenCalled();
    expect(deps.setMessages).toHaveBeenCalledTimes(2);
  });

  it('stages only a completed persisted interview derivation', async () => {
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
    );
    expect(deps.stageDraftSpec).toHaveBeenCalledWith(
      expect.objectContaining({
        interviewId: active.id,
        goal: 'Study liver fibrosis',
        attributes: ['Stellate-cell metabolism'],
        requirements: ['Human evidence'],
      }),
      expect.any(Number),
    );
  });

  it('handleEditPlan stages the spec and focuses the composer', () => {
    const deps = makeDeps();
    const handlers = buildChatHandlers(deps);
    const spec = makeSpec({goal: 'Edit target goal'});

    handlers.handleEditPlan(spec);

    expect(deps.stageDraftSpec).toHaveBeenCalledWith(spec);
    expect(deps.focusComposer).toHaveBeenCalledOnce();
  });

  it('handleRetryMessage re-appends the message content as a fresh assistant bubble', () => {
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

  it('handleRetryDraftSpec re-stages the persisted derivation', () => {
    const spec = makeSpec({goal: 'Study X', focus: 'prefer_novelty'});
    const deps = makeDeps({draft: {spec, createdAt: 1}});
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryDraftSpec();

    expect(deps.stageDraftSpec).toHaveBeenCalledWith(spec);
  });

  it('handleRetryDraftSpec is a no-op without a staged draft', () => {
    const deps = makeDeps({draft: null});
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryDraftSpec();

    expect(deps.stageDraftSpec).not.toHaveBeenCalled();
  });

  it('handleCancelDraftSpec resets state and shows a cancellation toast', () => {
    const deps = makeDeps({draft: {spec: makeSpec(), createdAt: 1}});
    const handlers = buildChatHandlers(deps);

    handlers.handleCancelDraftSpec();

    expect(deps.clearSessionState).toHaveBeenCalledOnce();
    expect(deps.setToast).toHaveBeenCalledWith('The session was canceled');
  });

  it('handleCopyRequest copies the prompt, and its toast action starts a new chat prefilled with it', async () => {
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

  it('handleEditMessage loads the message into the composer and focuses it', () => {
    const deps = makeDeps();
    const handlers = buildChatHandlers(deps);

    handlers.handleEditMessage(makeMessage({content: 'Original prompt'}));

    expect(deps.setInput).toHaveBeenCalledWith('Original prompt');
    expect(deps.focusComposer).toHaveBeenCalledOnce();
  });
});

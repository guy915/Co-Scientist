import {describe, expect, it, vi} from 'vitest';
import {buildChatHandlers} from './chat_session_handlers';
import type {HandlerDeps} from './chat_session_types';
import type {ChatEntry} from '../pages/chat_timeline_cards';
import type {InferredRunSpec} from '../run_spec';

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
    setInput: vi.fn(),
    draftSpec: null,
    draftSpecCreatedAt: null,
    setDraftSpec: vi.fn(),
    setDraftSpecCreatedAt: vi.fn(),
    setConfirmedSpec: vi.fn(),
    setConfirmedSpecCreatedAt: vi.fn(),
    setStartedSession: vi.fn(),
    setIsStarting: vi.fn(),
    setMessages: vi.fn(),
    setError: vi.fn(),
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

  it('handleRetryDraftSpec re-infers the draft from its goal when a draft exists', () => {
    const draftSpec = makeSpec({goal: 'Study X', focus: 'prefer_novelty'});
    const deps = makeDeps({draftSpec});
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryDraftSpec();

    expect(deps.stageDraftSpec).toHaveBeenCalledWith(
      expect.objectContaining({goal: 'Study X'}),
    );
  });

  it('handleRetryDraftSpec is a no-op without a staged draft', () => {
    const deps = makeDeps({draftSpec: null});
    const handlers = buildChatHandlers(deps);

    handlers.handleRetryDraftSpec();

    expect(deps.stageDraftSpec).not.toHaveBeenCalled();
  });

  it('handleCancelDraftSpec resets state and shows a cancellation toast', () => {
    const deps = makeDeps({draftSpec: makeSpec()});
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

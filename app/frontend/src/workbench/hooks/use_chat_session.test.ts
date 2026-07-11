import {type FormEvent} from 'react';
import {act, renderHook} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {useChatSession} from './use_chat_session';
import type {ChatEntry} from '../pages/chat_timeline_cards';

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {...actual, createRun: vi.fn(), startRun: vi.fn()};
});

const submitEvent = () =>
  ({preventDefault: () => undefined}) as unknown as FormEvent<HTMLFormElement>;

function makeDeps() {
  return {
    reloadHistory: vi.fn().mockResolvedValue(undefined),
    focusComposer: vi.fn(),
    setToast: vi.fn(),
    pubmedEnabled: true,
  };
}

function renderSession(deps = makeDeps()) {
  const hook = renderHook(() => useChatSession(deps));
  return {...hook, deps};
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useChatSession', () => {
  it('starts empty with no conversation', () => {
    const {result} = renderSession();
    expect(result.current.hasConversation).toBe(false);
    expect(result.current.draft).toBeNull();
    expect(result.current.messages).toHaveLength(0);
  });

  it('submitting a goal stages a draft spec and logs the user message', async () => {
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
    // The composer is cleared after submitting.
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

  it('submitting again while a draft exists revises it and adds a reply', async () => {
    const {result} = renderSession();

    act(() => result.current.setInput('Study MASLD fibrosis'));
    await act(async () => {
      await result.current.handleSubmit(submitEvent());
    });
    const afterFirst = result.current.messages.length;

    act(() => result.current.setInput('Focus on hepatic stellate cells'));
    await act(async () => {
      await result.current.handleSubmit(submitEvent());
    });

    expect(result.current.draft).not.toBeNull();
    // A user message plus an assistant acknowledgement were appended.
    expect(result.current.messages.length).toBe(afterFirst + 2);
    expect(result.current.messages.some(m => m.role === 'assistant')).toBe(
      true,
    );
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

  it('editing a message loads it into the composer and focuses it', () => {
    const {result, deps} = renderSession();
    const message: ChatEntry = {
      id: 'm1',
      role: 'user',
      content: 'Original prompt',
      created_at: 1,
    };

    act(() => result.current.handleEditMessage(message));

    expect(result.current.input).toBe('Original prompt');
    expect(deps.focusComposer).toHaveBeenCalledOnce();
  });

  it('starting a run creates it, records the session, and reloads history', async () => {
    vi.mocked(runsApi.createRun).mockResolvedValue({
      id: 'run-xyz',
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
});

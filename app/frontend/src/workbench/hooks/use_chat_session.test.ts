import {type FormEvent} from 'react';
import {act, renderHook} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {useChatSession} from './use_chat_session';
import type {ChatEntry} from '../pages/chat_timeline_cards';

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    createInterview: vi.fn(),
    addInterviewTurn: vi.fn(),
    createRun: vi.fn(),
    startRun: vi.fn(),
    uploadRunDocument: vi.fn(),
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
    turns: [],
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
    setToast: vi.fn(),
    pubmedEnabled: true,
    webSearchEnabled: true,
    paperCorpusEnabled: true,
    audience: null,
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

it('uploads staged scientific files before starting the run', async () => {
  const file = new File(['private result'], 'result.txt', {
    type: 'text/plain',
  });
  vi.mocked(runsApi.createRun).mockResolvedValue({
    id: 'run-with-file',
  } as Awaited<ReturnType<typeof runsApi.createRun>>);
  vi.mocked(runsApi.uploadRunDocument).mockResolvedValue({
    id: 'evidence-1',
    indexed: true,
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
  await act(async () => {
    await result.current.handleStartRun();
  });

  expect(runsApi.uploadRunDocument).toHaveBeenCalledWith('run-with-file', file);
  expect(runsApi.uploadRunDocument).toHaveBeenCalledBefore(
    vi.mocked(runsApi.startRun),
  );
});

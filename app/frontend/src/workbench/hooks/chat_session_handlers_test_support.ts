import {vi} from 'vitest';
import type {HandlerDeps} from './chat_session_types';
import type {Interview} from '@/api/runs';

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

export function makeDeps(overrides: Partial<HandlerDeps> = {}): HandlerDeps {
  return {
    input: '',
    interview: null,
    startedSession: null,
    setInterview: vi.fn(),
    onChatStarted: vi.fn(),
    setInput: vi.fn(),
    draft: null,
    setDraft: vi.fn(),
    setConfirmed: vi.fn(),
    setStartedSession: vi.fn(),
    setIsStarting: vi.fn(),
    setIsAwaitingAgent: vi.fn(),
    setAgentReasoning: vi.fn(),
    setAgentDraft: vi.fn(),
    turnAbortRef: {current: null},
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
    webSearchEnabled: true,
    ...overrides,
  };
}

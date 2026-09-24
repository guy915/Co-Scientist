import {type HandlerDeps} from './chat_session_types';
import {type InferredRunSpec} from '../run_spec';
import {createRun, getRun} from '@/api/runs';
import {vi} from 'vitest';

export const SPEC: InferredRunSpec = {
  goal: 'g',
  interviewId: 'chat-1',
  requirements: [],
  attributes: [],
  criteria: [],
  focus: 'balance',
  tier: 'standard',
};

export function deps(): HandlerDeps {
  return {
    draft: {spec: SPEC, createdAt: 0},
    pubmedEnabled: false,
    webSearchEnabled: false,
    reloadHistory: async () => undefined,
    setIsStarting: () => undefined,
    setError: () => undefined,
    setToast: () => undefined,
    setConfirmed: () => undefined,
    setDraft: () => undefined,
    setInput: () => undefined,
    setMessages: () => undefined,
    setStartedSession: () => undefined,
    setIsAwaitingAgent: () => undefined,
    turnAbortRef: {current: null},
    pendingAttachments: [],
    setPendingAttachments: () => undefined,
  } as unknown as HandlerDeps;
}

export function createPayload(goal: string) {
  return {
    research_goal: goal,
    interview_id: 'chat-1',
    requirements: [],
    attributes: [],
    criteria: [],
    focus: 'balance',
    tier: 'standard',
    notify_on_completion: false,
    completion_email: undefined,
    enable_literature_review: false,
    enable_web_search: false,
    document_ids: [],
  };
}

export function runRecord(
  id: string,
  status: string,
  goal: string,
  setup: Partial<{
    requirements: string[];
    attributes: string[];
    criteria: string[];
    focus: string;
    tier: string;
  }> = {},
) {
  return {
    id,
    status,
    research_goal: goal,
    config: {
      setup: {
        goal,
        requirements: [],
        attributes: [],
        criteria: [],
        focus: 'balance',
        tier: 'standard',
        ...setup,
      },
    },
  } as Awaited<ReturnType<typeof getRun>>;
}

export function createKeys() {
  return vi
    .mocked(createRun)
    .mock.calls.map(([, options]) => options?.idempotencyKey);
}

export function completedInterview(runId: string, goal: string) {
  return {
    id: 'chat-1',
    run_id: runId,
    status: 'completed',
    fields: {
      research_challenge: goal,
      focus_area: [],
      preferences: [],
      title: null,
    },
    turns: [
      {
        id: 4,
        role: 'agent',
        content: 'Plan ready.',
        reasoning: null,
        fallback: false,
        questions: [],
        created_at: 12,
      },
    ],
  } as unknown as NonNullable<HandlerDeps['interview']>;
}

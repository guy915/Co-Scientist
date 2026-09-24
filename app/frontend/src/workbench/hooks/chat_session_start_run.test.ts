import {beforeEach, describe, expect, it, vi} from 'vitest';
import {type InferredRunSpec} from '../run_spec';
import {type HandlerDeps} from './chat_session_types';

vi.mock('@/api/runs', () => ({
  createRun: vi.fn(async () => ({id: 'r1'})),
  startRun: vi.fn(async () => {}),
  announceRunStart: vi.fn(async () => null),
  uploadRunDocument: vi.fn(async () => {}),
}));

// Imported after the mock is registered so the module under test binds to it.
import {createRun} from '@/api/runs';
import {promoteDraftToRun} from './chat_session_start_run';

const SPEC: InferredRunSpec = {
  goal: 'g',
  interviewId: 'chat-1',
  requirements: [],
  attributes: [],
  criteria: [],
  focus: 'balance',
  tier: 'standard',
};

// The handler only reads a handful of HandlerDeps fields on the happy path;
// the no-op setters satisfy the rest without reconstructing view state.
function deps(): HandlerDeps {
  return {
    draft: {spec: SPEC, createdAt: 0},
    pubmedEnabled: false,
    webSearchEnabled: false,
    reloadHistory: async () => {},
    setIsStarting: () => {},
    setError: () => {},
    setToast: () => {},
    setConfirmed: () => {},
    setDraft: () => {},
    setInput: () => {},
    setMessages: () => {},
    setStartedSession: () => {},
    setIsAwaitingAgent: () => {},
    turnAbortRef: {current: null},
    pendingAttachments: [],
    setPendingAttachments: () => {},
  } as unknown as HandlerDeps;
}

describe('start run', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.clearAllMocks();
  });

  it('creates the run from the confirmed draft spec', async () => {
    await promoteDraftToRun(deps());
    expect(vi.mocked(createRun).mock.calls[0][0].research_goal).toBe(SPEC.goal);
  });

  it('reuses the exact create intent when a manual retry follows a lost response', async () => {
    vi.mocked(createRun)
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({id: 'r1'} as Awaited<
        ReturnType<typeof createRun>
      >);
    const session = deps();

    await promoteDraftToRun(session);
    await promoteDraftToRun(session);

    const first = vi.mocked(createRun).mock.calls[0];
    const second = vi.mocked(createRun).mock.calls[1];
    expect(first[0]).toEqual(second[0]);
    expect(first[0]).toEqual({
      research_goal: SPEC.goal,
      interview_id: 'chat-1',
      requirements: [],
      attributes: [],
      criteria: [],
      focus: 'balance',
      tier: 'standard',
      notify_on_completion: false,
      enable_literature_review: false,
      enable_web_search: false,
      document_ids: [],
    });
    expect(first[1]?.idempotencyKey).toBeTruthy();
    expect(second[1]?.idempotencyKey).toBe(first[1]?.idempotencyKey);
  });
});

it('freezes the whole closing turn, not just its spec', async () => {
  // The confirmed stage is the same turn the draft was, so it carries the
  // Agent's closing message and its thinking across the start. Dropping them
  // here is what made the plan turn lose its prose the moment the run began.
  const setConfirmed = vi.fn();
  const stage = {
    spec: SPEC,
    createdAt: 12,
    intro: 'The scope is settled.',
    reasoning: 'Every field is filled.',
    turnId: 4,
    fallback: true,
  };

  await promoteDraftToRun({
    ...deps(),
    draft: stage,
    setConfirmed,
  } as unknown as HandlerDeps);

  expect(setConfirmed).toHaveBeenCalledWith(stage);
});

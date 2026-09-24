import {beforeEach, describe, expect, it, vi} from 'vitest';
import {type InferredRunSpec} from '../run_spec';
import {type HandlerDeps} from './chat_session_types';

vi.mock('@/api/runs', () => ({
  createRun: vi.fn(async () => ({id: 'r1', status: 'draft'})),
  startRun: vi.fn(async () => {}),
  cancelRun: vi.fn(async (id: string) => ({id, status: 'cancelled'})),
  getRun: vi.fn(async (id: string) => ({id, status: 'draft'})),
  announceRunStart: vi.fn(async () => null),
  uploadRunDocument: vi.fn(async () => {}),
}));

// Imported after the mock is registered so the module under test binds to it.
import {cancelRun, createRun, getRun, startRun} from '@/api/runs';
import {
  getPendingCreateIntent,
  readPendingCreateIntent,
  rememberPendingCreateRun,
} from './chat_session_create_intent';
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
    vi.mocked(createRun).mockResolvedValue({
      id: 'r1',
      status: 'draft',
    } as Awaited<ReturnType<typeof createRun>>);
    vi.mocked(startRun).mockResolvedValue({
      id: 'r1',
      status: 'queued',
    });
    vi.mocked(cancelRun).mockImplementation(async id => ({
      id,
      status: 'cancelled',
    }));
    vi.mocked(getRun).mockResolvedValue({
      id: 'r1',
      status: 'draft',
    } as Awaited<ReturnType<typeof getRun>>);
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
    await promoteDraftToRun({
      ...session,
      draft: {
        spec: {...SPEC, goal: 'reconstructed after refresh'},
        createdAt: 10,
      },
      pubmedEnabled: true,
      webSearchEnabled: true,
      pendingAttachments: [{id: 'changed-doc'}],
    } as unknown as HandlerDeps);

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

  it('clears the pending key after a confirmed start', async () => {
    await promoteDraftToRun(deps());

    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('retires a created draft after confirmed cancellation so the next click creates a new run', async () => {
    vi.mocked(startRun).mockRejectedValueOnce(new Error('start rejected'));
    vi.mocked(getRun).mockResolvedValueOnce({
      id: 'r1',
      status: 'draft',
    } as Awaited<ReturnType<typeof getRun>>);

    const session = deps();
    await promoteDraftToRun(session);
    const firstKey = vi.mocked(createRun).mock.calls[0][1]?.idempotencyKey;
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();

    await promoteDraftToRun(session);

    expect(vi.mocked(createRun)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(createRun).mock.calls[1][1]?.idempotencyKey).not.toBe(
      firstKey,
    );
    expect(cancelRun).toHaveBeenCalledWith('r1');
  });

  it('treats a start error followed by a running status as already started', async () => {
    vi.mocked(startRun).mockRejectedValueOnce(new TypeError('connection lost'));
    vi.mocked(getRun).mockResolvedValueOnce({
      id: 'r1',
      status: 'running',
    } as Awaited<ReturnType<typeof getRun>>);
    const setStartedSession = vi.fn();

    await promoteDraftToRun({...deps(), setStartedSession});

    expect(vi.mocked(createRun)).toHaveBeenCalledTimes(1);
    expect(cancelRun).not.toHaveBeenCalled();
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
    expect(setStartedSession).toHaveBeenCalledWith(
      expect.objectContaining({id: 'r1', announcing: false}),
    );
  });

  it.each(['failed', 'blocked'] as const)(
    'surfaces a %s receipt without presenting it as a started session',
    async status => {
      vi.mocked(createRun).mockResolvedValueOnce({
        id: 'r1',
        status,
      } as Awaited<ReturnType<typeof createRun>>);
      vi.mocked(getRun).mockResolvedValue({
        id: 'r1',
        status,
      } as Awaited<ReturnType<typeof getRun>>);
      const session = deps();
      const setDraft = vi.fn();
      const setStartedSession = vi.fn();
      const setError = vi.fn();

      await promoteDraftToRun({
        ...session,
        setDraft,
        setStartedSession,
        setError,
      });
      await promoteDraftToRun({
        ...session,
        setDraft,
        setStartedSession,
        setError,
      });

      expect(createRun).toHaveBeenCalledTimes(1);
      expect(startRun).not.toHaveBeenCalled();
      expect(setStartedSession).not.toHaveBeenCalled();
      expect(setDraft).toHaveBeenCalledWith(session.draft);
      expect(setError).toHaveBeenCalledWith(
        expect.stringContaining(`existing run is ${status}`),
      );
      expect(await readPendingCreateIntent('chat-1')).toMatchObject({
        createdRunId: 'r1',
      });
    },
  );

  it('does not start a replayed create receipt that already reports a queued run', async () => {
    vi.mocked(createRun).mockResolvedValueOnce({
      id: 'r1',
      status: 'queued',
    } as Awaited<ReturnType<typeof createRun>>);

    await promoteDraftToRun(deps());

    expect(startRun).not.toHaveBeenCalled();
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('keeps an unresolved draft linked and retries that same run only after another click', async () => {
    vi.mocked(startRun).mockRejectedValueOnce(new TypeError('connection lost'));
    vi.mocked(cancelRun).mockRejectedValueOnce(
      new TypeError('cancel response lost'),
    );
    vi.mocked(getRun)
      .mockResolvedValueOnce({
        id: 'r1',
        status: 'draft',
      } as Awaited<ReturnType<typeof getRun>>)
      .mockResolvedValueOnce({
        id: 'r1',
        status: 'draft',
      } as Awaited<ReturnType<typeof getRun>>)
      .mockResolvedValueOnce({
        id: 'r1',
        status: 'draft',
      } as Awaited<ReturnType<typeof getRun>>);

    const session = deps();
    const stage = session.draft;
    const setDraft = vi.fn();
    const recoverableSession = {...session, setDraft};
    await promoteDraftToRun(recoverableSession);
    expect(await readPendingCreateIntent('chat-1')).toMatchObject({
      createdRunId: 'r1',
    });
    expect(vi.mocked(startRun)).toHaveBeenCalledTimes(1);
    expect(setDraft).toHaveBeenCalledWith(stage);

    await promoteDraftToRun(recoverableSession);

    expect(vi.mocked(createRun)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(startRun)).toHaveBeenCalledTimes(2);
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('uses the interview-linked draft after refresh without creating another run', async () => {
    const intent = await getPendingCreateIntent('chat-1', {
      research_goal: 'saved exact goal',
      interview_id: 'chat-1',
    });
    const refreshedDeps = {
      ...deps(),
      draft: null,
      interview: {
        id: 'chat-1',
        run_id: 'r1',
        status: 'completed',
        fields: {
          research_challenge: 'saved exact goal',
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
      },
    } as unknown as HandlerDeps;

    await promoteDraftToRun(refreshedDeps);

    expect(vi.mocked(createRun)).not.toHaveBeenCalled();
    expect(vi.mocked(getRun)).toHaveBeenCalledWith('r1');
    expect(vi.mocked(startRun)).toHaveBeenCalledWith('r1');
    expect(intent.key).toBeTruthy();
  });

  it('does not create a new key when an owned getRun lookup fails', async () => {
    const intent = await getPendingCreateIntent('chat-1', {
      research_goal: 'saved exact goal',
      interview_id: 'chat-1',
    });
    rememberPendingCreateRun('chat-1', intent.key, 'r1');
    vi.mocked(getRun).mockRejectedValueOnce(new Error('404 not found'));
    const session = deps();
    const linkedDeps = {
      ...session,
      draft: null,
      interview: {
        id: 'chat-1',
        run_id: 'r1',
        status: 'completed',
        fields: {
          research_challenge: 'saved exact goal',
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
      },
    } as unknown as HandlerDeps;

    await promoteDraftToRun(linkedDeps);

    expect(createRun).not.toHaveBeenCalled();
    expect(await readPendingCreateIntent('chat-1')).toMatchObject({
      key: intent.key,
      createdRunId: 'r1',
    });
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

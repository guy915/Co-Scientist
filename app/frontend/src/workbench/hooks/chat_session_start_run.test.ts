import {beforeEach, describe, expect, it, vi} from 'vitest';
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
import {
  completedInterview,
  createKeys,
  createPayload,
  deps,
  runRecord,
  SPEC,
} from './chat_session_start_run_test_support';
import {promoteDraftToRun} from './chat_session_start_run';

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

  it('resolves a lost create before starting a manually edited visible plan', async () => {
    vi.mocked(createRun)
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({id: 'r1', status: 'draft'} as Awaited<
        ReturnType<typeof createRun>
      >)
      .mockResolvedValueOnce({id: 'r2', status: 'draft'} as Awaited<
        ReturnType<typeof createRun>
      >);
    const session = deps();
    const editedDraft = {
      spec: {...SPEC, goal: 'edited visible plan'},
      createdAt: 10,
    };
    const setStartedSession = vi.fn();

    await promoteDraftToRun({...session, setStartedSession});
    await promoteDraftToRun({
      ...session,
      draft: editedDraft,
      pubmedEnabled: true,
      webSearchEnabled: true,
      pendingAttachments: [{id: 'changed-doc'}],
      setStartedSession,
    } as unknown as HandlerDeps);

    const [first, replay, edited] = vi.mocked(createRun).mock.calls;
    const keys = createKeys();
    expect(replay[0]).toEqual(first[0]);
    expect(keys[1]).toBe(keys[0]);
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
    expect(edited[0]).toEqual({
      research_goal: 'edited visible plan',
      interview_id: 'chat-1',
      requirements: [],
      attributes: [],
      criteria: [],
      focus: 'balance',
      tier: 'standard',
      notify_on_completion: false,
      enable_literature_review: true,
      enable_web_search: true,
      document_ids: ['changed-doc'],
    });
    expect(keys[2]).toBeTruthy();
    expect(keys[2]).not.toBe(keys[0]);
    expect(cancelRun).toHaveBeenCalledWith('r1');
    expect(startRun).toHaveBeenCalledTimes(1);
    expect(startRun).toHaveBeenCalledWith('r2');
    expect(setStartedSession).toHaveBeenCalledWith(
      expect.objectContaining({id: 'r2'}),
    );
  });

  it('clears the pending key after a confirmed start', async () => {
    await promoteDraftToRun(deps());

    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('retires a create intent rejected before commit so an edited draft gets a fresh key', async () => {
    vi.mocked(createRun)
      .mockRejectedValueOnce(
        Object.assign(new Error('unprocessable request'), {status: 422}),
      )
      .mockResolvedValueOnce({id: 'r2', status: 'draft'} as Awaited<
        ReturnType<typeof createRun>
      >);
    const session = deps();

    await promoteDraftToRun(session);
    const rejectedKey = vi.mocked(createRun).mock.calls[0][1]?.idempotencyKey;
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();

    await promoteDraftToRun({
      ...session,
      draft: {spec: {...SPEC, goal: 'corrected plan'}, createdAt: 10},
    });

    expect(vi.mocked(createRun).mock.calls[1][0].research_goal).toBe(
      'corrected plan',
    );
    expect(vi.mocked(createRun).mock.calls[1][1]?.idempotencyKey).not.toBe(
      rejectedKey,
    );
    expect(startRun).toHaveBeenCalledWith('r2');
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
      .mockResolvedValueOnce(runRecord('r1', 'draft', 'g'))
      .mockResolvedValueOnce(runRecord('r1', 'draft', 'g'))
      .mockResolvedValueOnce(runRecord('r1', 'draft', 'g'));

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

  it('continues a linked draft with saved attachments after refresh defaults reset', async () => {
    vi.mocked(createRun).mockRejectedValueOnce(
      new TypeError('Failed to fetch'),
    );
    const originalDeps = {
      ...deps(),
      pendingAttachments: [{id: 'doc-1'}],
    } as unknown as HandlerDeps;

    await promoteDraftToRun(originalDeps);
    expect(vi.mocked(createRun).mock.calls[0][0]).toMatchObject({
      document_ids: ['doc-1'],
      enable_literature_review: false,
      enable_web_search: false,
    });

    vi.mocked(getRun).mockResolvedValueOnce(
      runRecord('r1', 'draft', 'g', {
        requirements: ['server persisted requirement'],
        focus: 'prefer_novelty',
        tier: 'express',
      }),
    );
    const setConfirmed = vi.fn();
    const refreshedDeps = {
      ...deps(),
      draft: null,
      pubmedEnabled: true,
      webSearchEnabled: true,
      interview: completedInterview('r1', 'g'),
      setConfirmed,
    } as unknown as HandlerDeps;

    await promoteDraftToRun(refreshedDeps);

    expect(createRun).toHaveBeenCalledTimes(1);
    expect(getRun).toHaveBeenCalledWith('r1');
    expect(cancelRun).not.toHaveBeenCalled();
    expect(startRun).toHaveBeenCalledTimes(1);
    expect(startRun).toHaveBeenCalledWith('r1');
    expect(setConfirmed).toHaveBeenCalledWith(
      expect.objectContaining({
        spec: expect.objectContaining({
          goal: 'g',
          requirements: ['server persisted requirement'],
          focus: 'prefer_novelty',
          tier: 'express',
        }),
      }),
    );
  });

  it('does not create a new key when an owned getRun lookup fails', async () => {
    const intent = await getPendingCreateIntent('chat-1', {
      ...createPayload('saved exact goal'),
      document_ids: ['doc-1'],
    });
    rememberPendingCreateRun('chat-1', intent.key, 'r1');
    vi.mocked(getRun).mockRejectedValueOnce(new Error('404 not found'));
    const session = deps();
    const linkedDeps = {
      ...session,
      draft: null,
      pubmedEnabled: true,
      webSearchEnabled: true,
      interview: completedInterview('r1', 'saved exact goal'),
    } as unknown as HandlerDeps;

    await promoteDraftToRun(linkedDeps);

    expect(createRun).not.toHaveBeenCalled();
    expect(await readPendingCreateIntent('chat-1')).toMatchObject({
      key: intent.key,
      createdRunId: 'r1',
    });
  });

  it('shows the saved plan when retry finds that it already started', async () => {
    const intent = await getPendingCreateIntent(
      'chat-1',
      createPayload('saved exact goal'),
    );
    vi.mocked(createRun).mockResolvedValueOnce(
      runRecord('r1', 'running', 'saved exact goal'),
    );
    const setConfirmed = vi.fn();
    const setStartedSession = vi.fn();

    await promoteDraftToRun({
      ...deps(),
      draft: {spec: {...SPEC, goal: 'edited visible plan'}, createdAt: 10},
      setConfirmed,
      setStartedSession,
    });

    expect(vi.mocked(createRun)).toHaveBeenCalledWith(intent.payload, {
      idempotencyKey: intent.key,
    });
    expect(startRun).not.toHaveBeenCalled();
    expect(setConfirmed).toHaveBeenCalledWith(
      expect.objectContaining({
        spec: expect.objectContaining({goal: 'saved exact goal'}),
      }),
    );
    expect(setStartedSession).toHaveBeenCalledWith(
      expect.objectContaining({id: 'r1', title: 'saved exact goal'}),
    );
  });
});

it('freezes the whole closing turn, not just its spec', async () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.clearAllMocks();
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

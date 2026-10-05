import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {SessionState} from './use_chat_session';
import {sessionRuntime, stagedDocument} from './__tests__/session_helpers';
import {cancelRun, createRun, getRun, startRun} from '@/api/runs';
import {
  getPendingCreateIntent,
  readPendingCreateIntent,
  rememberPendingCreateRun,
  promoteDraftToRun,
} from './chat_session_start_run';
import type {InferredRunSpec} from '../run_spec';

vi.mock('@/api/runs', async importActual => ({
  ...(await importActual<typeof import('@/api/runs')>()),
  createRun: vi.fn(),
  startRun: vi.fn(),
  cancelRun: vi.fn(),
  getRun: vi.fn(),
  announceRunStart: vi.fn(async () => null),
}));

const SPEC: InferredRunSpec = {
  goal: 'g',
  interviewId: 'chat-1',
  requirements: [],
  attributes: [],
  criteria: [],
  focus: 'balance',
  tier: 'standard',
};

function deps(state: Partial<SessionState> = {}) {
  return sessionRuntime(
    {draft: {spec: SPEC, createdAt: 0}, ...state},
    {pubmedEnabled: false, webSearchEnabled: false},
  );
}

function runRecord(
  id: string,
  status: string,
  goal = 'g',
  setup: Record<string, unknown> = {},
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
  } as unknown as Awaited<ReturnType<typeof getRun>>;
}

function completedInterview(runId: string, goal: string) {
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
  } as unknown as NonNullable<SessionState['interview']>;
}

function createKeys() {
  return vi
    .mocked(createRun)
    .mock.calls.map(([, options]) => options?.idempotencyKey);
}

function savedIntent(goal: string, documentIds: string[] = []) {
  return getPendingCreateIntent('chat-1', {
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
    document_ids: documentIds,
  });
}

describe('start run', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.resetAllMocks();
    vi.mocked(createRun).mockResolvedValue(runRecord('r1', 'draft') as never);
    vi.mocked(startRun).mockResolvedValue({id: 'r1', status: 'queued'});
    vi.mocked(cancelRun).mockImplementation(async id => ({
      id,
      status: 'cancelled',
    }));
    vi.mocked(getRun).mockResolvedValue(runRecord('r1', 'draft'));
  });

  it('sends the confirmed plan and staged documents under one idempotency key, then clears it', async () => {
    await promoteDraftToRun(deps({pendingAttachments: [stagedDocument('d1')]}));

    const [payload, options] = vi.mocked(createRun).mock.calls[0];
    expect(payload).toStrictEqual({
      research_goal: 'g',
      interview_id: 'chat-1',
      requirements: [],
      attributes: [],
      criteria: [],
      focus: 'balance',
      tier: 'standard',
      notify_on_completion: false,
      enable_literature_review: false,
      enable_web_search: false,
      document_ids: ['d1'],
    });
    expect(options).toEqual({
      idempotencyKey: expect.stringMatching(/^run-create-/),
    });
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('resolves a lost create before starting a manually edited visible plan', async () => {
    vi.mocked(createRun)
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(runRecord('r1', 'draft') as never)
      .mockResolvedValueOnce(runRecord('r2', 'draft') as never);
    const session = deps();

    await promoteDraftToRun(session);
    session.update({
      draft: {spec: {...SPEC, goal: 'edited visible plan'}, createdAt: 10},
      pendingAttachments: [stagedDocument('changed-doc')],
    });
    session.services.pubmedEnabled = true;
    session.services.webSearchEnabled = true;
    await promoteDraftToRun(session);

    const [first, replay, edited] = vi.mocked(createRun).mock.calls;
    const keys = createKeys();
    expect(replay[0]).toEqual(first[0]);
    expect(keys[1]).toBe(keys[0]);
    expect(edited[0]).toMatchObject({
      research_goal: 'edited visible plan',
      enable_literature_review: true,
      enable_web_search: true,
      document_ids: ['changed-doc'],
    });
    expect(keys[2]).toBeTruthy();
    expect(keys[2]).not.toBe(keys[0]);
    expect(cancelRun).toHaveBeenCalledWith('r1');
    expect(startRun).toHaveBeenCalledTimes(1);
    expect(startRun).toHaveBeenCalledWith('r2');
    expect(session.state.startedSession?.id).toBe('r2');
  });

  it('retires a create intent rejected before commit so an edited draft gets a fresh key', async () => {
    vi.mocked(createRun)
      .mockRejectedValueOnce(
        Object.assign(new Error('unprocessable request'), {status: 422}),
      )
      .mockResolvedValueOnce(runRecord('r2', 'draft') as never);
    const session = deps();

    await promoteDraftToRun(session);
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
    session.update({
      draft: {spec: {...SPEC, goal: 'corrected plan'}, createdAt: 10},
    });
    await promoteDraftToRun(session);

    const keys = createKeys();
    expect(keys[1]).not.toBe(keys[0]);
    expect(startRun).toHaveBeenCalledWith('r2');
  });

  it('retires a created draft after confirmed cancellation so the next click creates a new run', async () => {
    vi.mocked(startRun).mockRejectedValueOnce(new Error('start rejected'));
    const session = deps();

    await promoteDraftToRun(session);
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
    await promoteDraftToRun(session);

    const keys = createKeys();
    expect(keys).toHaveLength(2);
    expect(keys[1]).not.toBe(keys[0]);
    expect(cancelRun).toHaveBeenCalledWith('r1');
    expect(session.state.error).toBeNull();
  });

  it('treats a start error followed by a running status as already started', async () => {
    vi.mocked(startRun).mockRejectedValueOnce(new TypeError('connection lost'));
    vi.mocked(getRun).mockResolvedValueOnce(runRecord('r1', 'running'));
    const session = deps();

    await promoteDraftToRun(session);

    expect(createRun).toHaveBeenCalledTimes(1);
    expect(cancelRun).not.toHaveBeenCalled();
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
    expect(session.state.startedSession).toMatchObject({
      id: 'r1',
      announcing: false,
    });
  });

  it.each(['failed', 'blocked'] as const)(
    'surfaces a %s receipt without presenting it as a started session',
    async status => {
      vi.mocked(createRun).mockResolvedValueOnce(
        runRecord('r1', status) as never,
      );
      vi.mocked(getRun).mockResolvedValue(runRecord('r1', status));
      const session = deps();
      const stage = session.state.draft;

      await promoteDraftToRun(session);
      await promoteDraftToRun(session);

      expect(createRun).toHaveBeenCalledTimes(1);
      expect(startRun).not.toHaveBeenCalled();
      expect(session.state.startedSession).toBeNull();
      expect(session.state.draft).toBe(stage);
      expect(session.state.error).toContain(`existing run is ${status}`);
      expect(await readPendingCreateIntent('chat-1')).toMatchObject({
        createdRunId: 'r1',
      });
    },
  );

  it('does not start a replayed create receipt that already reports a queued run', async () => {
    vi.mocked(createRun).mockResolvedValueOnce(
      runRecord('r1', 'queued') as never,
    );

    await promoteDraftToRun(deps());

    expect(startRun).not.toHaveBeenCalled();
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('keeps an unresolved draft linked and retries that same run only after another click', async () => {
    vi.mocked(startRun).mockRejectedValueOnce(new TypeError('connection lost'));
    vi.mocked(cancelRun).mockRejectedValueOnce(new TypeError('cancel lost'));
    const session = deps();
    const stage = session.state.draft;

    await promoteDraftToRun(session);
    expect(await readPendingCreateIntent('chat-1')).toMatchObject({
      createdRunId: 'r1',
    });
    expect(session.state.draft).toBe(stage);

    await promoteDraftToRun(session);

    expect(createRun).toHaveBeenCalledTimes(1);
    expect(startRun).toHaveBeenCalledTimes(2);
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('continues a linked draft with saved attachments after refresh defaults reset', async () => {
    vi.mocked(createRun).mockRejectedValueOnce(
      new TypeError('Failed to fetch'),
    );
    await promoteDraftToRun(
      deps({pendingAttachments: [stagedDocument('doc-1')]}),
    );
    expect(vi.mocked(createRun).mock.calls[0][0]).toMatchObject({
      document_ids: ['doc-1'],
    });

    vi.mocked(getRun).mockResolvedValueOnce(
      runRecord('r1', 'draft', 'g', {
        requirements: ['server persisted requirement'],
        focus: 'prefer_novelty',
        tier: 'express',
      }),
    );
    const refreshed = deps({
      draft: null,
      interview: completedInterview('r1', 'g'),
    });
    refreshed.services.pubmedEnabled = true;
    refreshed.services.webSearchEnabled = true;

    await promoteDraftToRun(refreshed);

    expect(createRun).toHaveBeenCalledTimes(1);
    expect(cancelRun).not.toHaveBeenCalled();
    expect(startRun).toHaveBeenCalledWith('r1');
    expect(refreshed.state.confirmed?.spec).toMatchObject({
      goal: 'g',
      requirements: ['server persisted requirement'],
      focus: 'prefer_novelty',
      tier: 'express',
    });
  });

  it('does not create a new key when an owned getRun lookup fails', async () => {
    const intent = await savedIntent('saved exact goal', ['doc-1']);
    rememberPendingCreateRun('chat-1', intent.key, 'r1');
    vi.mocked(getRun).mockRejectedValueOnce(new Error('404 not found'));

    await promoteDraftToRun(
      deps({
        draft: null,
        interview: completedInterview('r1', 'saved exact goal'),
      }),
    );

    expect(createRun).not.toHaveBeenCalled();
    expect(await readPendingCreateIntent('chat-1')).toMatchObject({
      key: intent.key,
      createdRunId: 'r1',
    });
  });

  it('shows the saved plan when retry finds that it already started', async () => {
    const intent = await savedIntent('saved exact goal');
    vi.mocked(createRun).mockResolvedValueOnce(
      runRecord('r1', 'running', 'saved exact goal') as never,
    );
    const session = deps({
      draft: {spec: {...SPEC, goal: 'edited visible plan'}, createdAt: 10},
    });

    await promoteDraftToRun(session);

    expect(createRun).toHaveBeenCalledWith(intent.payload, {
      idempotencyKey: intent.key,
    });
    expect(startRun).not.toHaveBeenCalled();
    expect(session.state.confirmed?.spec.goal).toBe('saved exact goal');
    expect(session.state.startedSession).toMatchObject({
      id: 'r1',
      title: 'saved exact goal',
    });
  });

  it('freezes the whole closing turn, not just its spec', async () => {
    const stage = {
      spec: SPEC,
      createdAt: 12,
      intro: 'The scope is settled.',
      reasoning: 'Every field is filled.',
      turnId: 4,
      fallback: true,
    };
    const session = deps({draft: stage});

    await promoteDraftToRun(session);

    expect(session.state.confirmed).toBe(stage);
  });
});

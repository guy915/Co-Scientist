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
  createRun: vi.fn(async () => ({id: 'r1', status: 'draft'})),
  startRun: vi.fn(async () => {}),
  cancelRun: vi.fn(async (id: string) => ({id, status: 'cancelled'})),
  getRun: vi.fn(async (id: string) => ({id, status: 'draft'})),
  announceRunStart: vi.fn(async () => null),
  uploadRunDocument: vi.fn(async () => {}),
}));

// Register the mock before importing the module that binds it.

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
    await promoteDraftToRun(session);
    session.update({
      draft: editedDraft,
      pendingAttachments: [stagedDocument('changed-doc')],
    });
    session.services.pubmedEnabled = true;
    session.services.webSearchEnabled = true;
    await promoteDraftToRun(session);

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
    expect(session.state.startedSession?.id).toBe('r2');
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

    session.update({
      draft: {spec: {...SPEC, goal: 'corrected plan'}, createdAt: 10},
    });
    await promoteDraftToRun(session);

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
    const session = deps();
    await promoteDraftToRun(session);

    expect(vi.mocked(createRun)).toHaveBeenCalledTimes(1);
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
      vi.mocked(createRun).mockResolvedValueOnce({
        id: 'r1',
        status,
      } as Awaited<ReturnType<typeof createRun>>);
      vi.mocked(getRun).mockResolvedValue(runRecord('r1', status, SPEC.goal));
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
    const stage = session.state.draft;
    const recoverableSession = session;
    await promoteDraftToRun(recoverableSession);
    expect(await readPendingCreateIntent('chat-1')).toMatchObject({
      createdRunId: 'r1',
    });
    expect(vi.mocked(startRun)).toHaveBeenCalledTimes(1);
    expect(session.state.draft).toBe(stage);

    await promoteDraftToRun(recoverableSession);

    expect(vi.mocked(createRun)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(startRun)).toHaveBeenCalledTimes(2);
    expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
  });

  it('continues a linked draft with saved attachments after refresh defaults reset', async () => {
    vi.mocked(createRun).mockRejectedValueOnce(
      new TypeError('Failed to fetch'),
    );
    const originalDeps = deps({pendingAttachments: [stagedDocument('doc-1')]});

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
    const refreshedDeps = deps({
      draft: null,
      interview: completedInterview('r1', 'g'),
    });
    refreshedDeps.services.pubmedEnabled = true;
    refreshedDeps.services.webSearchEnabled = true;

    await promoteDraftToRun(refreshedDeps);

    expect(createRun).toHaveBeenCalledTimes(1);
    expect(getRun).toHaveBeenCalledWith('r1');
    expect(cancelRun).not.toHaveBeenCalled();
    expect(startRun).toHaveBeenCalledTimes(1);
    expect(startRun).toHaveBeenCalledWith('r1');
    expect(refreshedDeps.state.confirmed?.spec).toMatchObject({
      goal: 'g',
      requirements: ['server persisted requirement'],
      focus: 'prefer_novelty',
      tier: 'express',
    });
  });

  it('does not create a new key when an owned getRun lookup fails', async () => {
    const intent = await getPendingCreateIntent('chat-1', {
      ...createPayload('saved exact goal'),
      document_ids: ['doc-1'],
    });
    rememberPendingCreateRun('chat-1', intent.key, 'r1');
    vi.mocked(getRun).mockRejectedValueOnce(new Error('404 not found'));
    const linkedDeps = deps({
      draft: null,
      interview: completedInterview('r1', 'saved exact goal'),
    });
    linkedDeps.services.pubmedEnabled = true;
    linkedDeps.services.webSearchEnabled = true;

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
    const session = deps({
      draft: {spec: {...SPEC, goal: 'edited visible plan'}, createdAt: 10},
    });
    await promoteDraftToRun(session);

    expect(vi.mocked(createRun)).toHaveBeenCalledWith(intent.payload, {
      idempotencyKey: intent.key,
    });
    expect(startRun).not.toHaveBeenCalled();
    expect(session.state.confirmed?.spec.goal).toBe('saved exact goal');
    expect(session.state.startedSession).toMatchObject({
      id: 'r1',
      title: 'saved exact goal',
    });
  });
});

it('freezes the whole closing turn, not just its spec', async () => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.clearAllMocks();
  // The draft and confirmed card share one closing turn; retain its prose and
  // reasoning.
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

export const SPEC: InferredRunSpec = {
  goal: 'g',
  interviewId: 'chat-1',
  requirements: [],
  attributes: [],
  criteria: [],
  focus: 'balance',
  tier: 'standard',
};

export function deps(state: Partial<SessionState> = {}) {
  return sessionRuntime(
    {draft: {spec: SPEC, createdAt: 0}, ...state},
    {
      pubmedEnabled: false,
      webSearchEnabled: false,
    },
  );
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
  } as unknown as NonNullable<SessionState['interview']>;
}

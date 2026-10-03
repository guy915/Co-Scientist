import {beforeEach, expect, it, vi} from 'vitest';
import {type InferredRunSpec} from '../run_spec';
import {type HandlerDeps} from './use_chat_session';

// Spread the real module so the pure status questions stay real and only the
// network calls are faked.
vi.mock('@/api/runs', async importActual => ({
  ...(await importActual<typeof import('@/api/runs')>()),
  createRun: vi.fn(async () => ({id: 'r1', status: 'draft'})),
  startRun: vi.fn(async () => {}),
  cancelRun: vi.fn(async (id: string) => ({id, status: 'cancelled'})),
  getRun: vi.fn(async (id: string) => ({id, status: 'draft'})),
}));

// Imported after the mock is registered so the module under test binds to it.
import {cancelRun, createRun, getRun, startRun} from '@/api/runs';
import {readPendingCreateIntent} from './chat_session_start_run';
import {promoteDraftToRun} from './chat_session_start_run';

const SPEC: InferredRunSpec = {
  interviewId: 'chat-1',
  goal: 'g',
  requirements: [],
  attributes: [],
  criteria: [],
  focus: 'balance',
  tier: 'standard',
};

interface Recorded {
  errors: string[];
  drafts: unknown[];
}

// The handler reads a handful of HandlerDeps fields; the no-op setters
// satisfy the rest without reconstructing view state. `recorded` captures
// the two transitions the failure path has to make.
function deps(
  recorded: Recorded,
  attachments: {id: string}[] = [],
): HandlerDeps {
  return {
    draft: {spec: SPEC, createdAt: 0},
    pubmedEnabled: false,
    webSearchEnabled: false,
    reloadHistory: async () => {},
    setIsStarting: () => {},
    setError: (message: string) => recorded.errors.push(message),
    setToast: () => {},
    setConfirmed: () => {},
    setDraft: (stage: unknown) => recorded.drafts.push(stage),
    setInput: () => {},
    setMessages: () => {},
    setStartedSession: () => {},
    pendingAttachments: attachments,
    setPendingAttachments: () => {},
  } as unknown as HandlerDeps;
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.clearAllMocks();
});

it('sends staged document ids with the run it creates', async () => {
  await promoteDraftToRun(deps({errors: [], drafts: []}, [{id: 'doc-1'}]));
  const [payload, options] = vi.mocked(createRun).mock.calls[0];
  expect(payload).toStrictEqual({
    research_goal: SPEC.goal,
    interview_id: SPEC.interviewId,
    document_ids: ['doc-1'],
    requirements: [],
    attributes: [],
    criteria: [],
    focus: 'balance',
    tier: 'standard',
    notify_on_completion: false,
    enable_literature_review: false,
    enable_web_search: false,
  });
  expect(options).toEqual({
    idempotencyKey: expect.stringMatching(/^run-create-/),
  });
});

it('settles the created run when starting it fails', async () => {
  vi.mocked(startRun).mockRejectedValueOnce(new Error('quota reached'));
  vi.mocked(getRun).mockResolvedValueOnce({
    id: 'r1',
    status: 'draft',
  } as Awaited<ReturnType<typeof getRun>>);
  const recorded: Recorded = {errors: [], drafts: []};

  await promoteDraftToRun(deps(recorded));

  // Rolled back: the run that was created but never started is settled,
  // rather than left as a draft nothing points at.
  expect(cancelRun).toHaveBeenCalledWith('r1');
  // Surfaced: the error names the run, and the plan is staged again so the
  // scientist can retry rather than losing the specification.
  expect(recorded.errors.join(' ')).toContain('quota reached');
  expect(recorded.drafts.at(-1)).toEqual({spec: SPEC, createdAt: 0});
  expect(await readPendingCreateIntent('chat-1')).toBeUndefined();
});

it('leaves nothing behind when creating the run fails', async () => {
  vi.mocked(createRun).mockRejectedValueOnce(new Error('bad document'));
  const recorded: Recorded = {errors: [], drafts: []};

  await promoteDraftToRun(deps(recorded));

  expect(cancelRun).not.toHaveBeenCalled();
  expect(startRun).not.toHaveBeenCalled();
  expect(recorded.errors.join(' ')).toContain('bad document');
});

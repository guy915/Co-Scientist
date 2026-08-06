import {beforeEach, expect, it, vi} from 'vitest';
import {type InferredRunSpec} from '../run_spec';
import {type HandlerDeps} from './chat_session_types';

vi.mock('@/api/runs', () => ({
  createRun: vi.fn(async () => ({id: 'r1'})),
  startRun: vi.fn(async () => {}),
  cancelRun: vi.fn(async () => {}),
}));

// Imported after the mock is registered so the module under test binds to it.
import {cancelRun, createRun, startRun} from '@/api/runs';
import {promoteDraftToRun} from './chat_session_start_run';

const SPEC: InferredRunSpec = {
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
  vi.clearAllMocks();
});

it('sends staged document ids with the run it creates', async () => {
  await promoteDraftToRun(deps({errors: [], drafts: []}, [{id: 'doc-1'}]));
  expect(vi.mocked(createRun).mock.calls[0][0].document_ids).toEqual(['doc-1']);
});

it('settles the created run when starting it fails', async () => {
  vi.mocked(startRun).mockRejectedValueOnce(new Error('quota reached'));
  const recorded: Recorded = {errors: [], drafts: []};

  await promoteDraftToRun(deps(recorded));

  // Rolled back: the run that was created but never started is settled,
  // rather than left as a draft nothing points at.
  expect(cancelRun).toHaveBeenCalledWith('r1');
  // Surfaced: the error names the run, and the plan is staged again so the
  // scientist can retry rather than losing the specification.
  expect(recorded.errors.join(' ')).toContain('quota reached');
  expect(recorded.drafts.at(-1)).toEqual({spec: SPEC, createdAt: 0});
});

it('leaves nothing behind when creating the run fails', async () => {
  vi.mocked(createRun).mockRejectedValueOnce(new Error('bad document'));
  const recorded: Recorded = {errors: [], drafts: []};

  await promoteDraftToRun(deps(recorded));

  expect(cancelRun).not.toHaveBeenCalled();
  expect(startRun).not.toHaveBeenCalled();
  expect(recorded.errors.join(' ')).toContain('bad document');
});

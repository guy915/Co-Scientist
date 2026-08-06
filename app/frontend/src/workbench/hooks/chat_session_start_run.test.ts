import {beforeEach, describe, expect, it, vi} from 'vitest';
import {type InferredRunSpec} from '../run_spec';
import {type HandlerDeps} from './chat_session_types';

vi.mock('@/api/runs', () => ({
  createRun: vi.fn(async () => ({id: 'r1'})),
  startRun: vi.fn(async () => {}),
  uploadRunDocument: vi.fn(async () => {}),
}));

// Imported after the mock is registered so the module under test binds to it.
import {createRun} from '@/api/runs';
import {promoteDraftToRun} from './chat_session_start_run';

const SPEC: InferredRunSpec = {
  goal: 'g',
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
    reloadHistory: async () => {},
    setIsStarting: () => {},
    setError: () => {},
    setToast: () => {},
    setConfirmed: () => {},
    setDraft: () => {},
    setInput: () => {},
    setMessages: () => {},
    setStartedSession: () => {},
    pendingAttachments: [],
    setPendingAttachments: () => {},
  } as unknown as HandlerDeps;
}

describe('start run forwards audience', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('sends the stored audience on createRun', async () => {
    window.localStorage.setItem('cosci-audience', 'sbi_ucd');
    await promoteDraftToRun(deps());
    expect(vi.mocked(createRun).mock.calls[0][0].audience).toBe('sbi_ucd');
  });

  it('sends no audience when none is stored', async () => {
    await promoteDraftToRun(deps());
    expect(vi.mocked(createRun).mock.calls[0][0].audience).toBeUndefined();
  });
});

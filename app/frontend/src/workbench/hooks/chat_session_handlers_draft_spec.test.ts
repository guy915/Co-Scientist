import {beforeEach, expect, test, vi} from 'vitest';
import {retryInterviewTurn} from '@/api/runs';
import {buildChatHandlers} from './chat_session_handlers';
import {makeDeps, makeInterview} from './chat_session_handlers_test_support';
import {makeSpec} from '@/test_fixtures';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {
    ...actual,
    createInterview: vi.fn(),
    addInterviewTurn: vi.fn(),
    retryInterviewTurn: vi.fn(),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

test('handleEditPlan stages the spec and focuses the composer', () => {
  const deps = makeDeps();
  const handlers = buildChatHandlers(deps);
  const spec = makeSpec({goal: 'Edit target goal'});

  handlers.handleEditPlan(spec);

  expect(deps.stageDraftSpec).toHaveBeenCalledWith(spec);
  expect(deps.focusComposer).toHaveBeenCalledOnce();
});

test('handleRetryDraftSpec re-derives the plan from its own turn', () => {
  const spec = makeSpec({goal: 'Study X', focus: 'prefer_novelty'});
  const deps = makeDeps({
    interview: makeInterview(),
    draft: {spec, createdAt: 1, turnId: 9},
  });
  const handlers = buildChatHandlers(deps);

  handlers.handleRetryDraftSpec();

  // Re-staging the spec already in hand could not change anything, so the
  // control read as dead; retry means asking that turn again.
  expect(retryInterviewTurn).toHaveBeenCalledWith(
    'interview-1',
    9,
    expect.objectContaining({
      onReasoning: expect.any(Function),
      onProse: expect.any(Function),
    }),
  );
  expect(deps.setDraft).toHaveBeenCalledWith(null);
});

test('handleRetryDraftSpec is a no-op without a staged draft', () => {
  const deps = makeDeps({interview: makeInterview(), draft: null});
  const handlers = buildChatHandlers(deps);

  handlers.handleRetryDraftSpec();

  expect(retryInterviewTurn).not.toHaveBeenCalled();
});

test('handleCancelDraftSpec resets state and shows a cancel toast', () => {
  const deps = makeDeps({draft: {spec: makeSpec(), createdAt: 1}});
  const handlers = buildChatHandlers(deps);

  handlers.handleCancelDraftSpec();

  expect(deps.clearSessionState).toHaveBeenCalledOnce();
  expect(deps.setToast).toHaveBeenCalledWith('The session was canceled');
});

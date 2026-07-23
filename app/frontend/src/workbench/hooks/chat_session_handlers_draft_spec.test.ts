import {expect, test, vi} from 'vitest';
import {buildChatHandlers} from './chat_session_handlers';
import {makeDeps} from './chat_session_handlers_test_support';
import {makeSpec} from '@/test_fixtures';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {...actual, createInterview: vi.fn(), addInterviewTurn: vi.fn()};
});

test('handleEditPlan stages the spec and focuses the composer', () => {
  const deps = makeDeps();
  const handlers = buildChatHandlers(deps);
  const spec = makeSpec({goal: 'Edit target goal'});

  handlers.handleEditPlan(spec);

  expect(deps.stageDraftSpec).toHaveBeenCalledWith(spec);
  expect(deps.focusComposer).toHaveBeenCalledOnce();
});

test('handleRetryDraftSpec re-stages the persisted derivation', () => {
  const spec = makeSpec({goal: 'Study X', focus: 'prefer_novelty'});
  const deps = makeDeps({draft: {spec, createdAt: 1}});
  const handlers = buildChatHandlers(deps);

  handlers.handleRetryDraftSpec();

  expect(deps.stageDraftSpec).toHaveBeenCalledWith(spec);
});

test('handleRetryDraftSpec is a no-op without a staged draft', () => {
  const deps = makeDeps({draft: null});
  const handlers = buildChatHandlers(deps);

  handlers.handleRetryDraftSpec();

  expect(deps.stageDraftSpec).not.toHaveBeenCalled();
});

test('handleCancelDraftSpec resets state and shows a cancel toast', () => {
  const deps = makeDeps({draft: {spec: makeSpec(), createdAt: 1}});
  const handlers = buildChatHandlers(deps);

  handlers.handleCancelDraftSpec();

  expect(deps.clearSessionState).toHaveBeenCalledOnce();
  expect(deps.setToast).toHaveBeenCalledWith('The session was canceled');
});

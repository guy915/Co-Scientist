import {expect, test, vi} from 'vitest';
import {buildChatHandlers} from './chat_session_handlers';
import {makeDeps, makeInterview} from './chat_session_handlers_test_support';
import {addInterviewTurn, createInterview} from '@/api/runs';

vi.mock('@/api/runs', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/runs')>();
  return {...actual, createInterview: vi.fn(), addInterviewTurn: vi.fn()};
});

test('starts a model-driven interview with no local draft', async () => {
  const interview = makeInterview();
  vi.mocked(createInterview).mockResolvedValue(interview);
  const deps = makeDeps({input: 'Study liver fibrosis'});
  const handlers = buildChatHandlers(deps);

  await handlers.handleSubmit({preventDefault: vi.fn()} as never);

  // The trailing sink is how the turn's live reasoning reaches the UI, and
  // the audience rides along so the Agent is briefed on the scientist's
  // group; undefined here because this fixture declares no audience.
  expect(createInterview).toHaveBeenCalledWith(
    'Study liver fibrosis',
    expect.any(Function),
    undefined,
  );
  expect(deps.setInterview).toHaveBeenCalledWith(interview);
  expect(deps.stageDraftSpec).not.toHaveBeenCalled();
  expect(deps.setMessages).toHaveBeenCalledTimes(2);
});

test('conducts the interview under the declared audience', async () => {
  // Regression: the interview was the one conversational surface that never
  // received the audience, so in SBI mode the Agent denied knowing the lab
  // it was supposedly briefed on.
  vi.mocked(createInterview).mockResolvedValue(makeInterview());
  const deps = makeDeps({
    input: 'Study liver fibrosis',
    audience: 'sbi_ucd',
  });

  await buildChatHandlers(deps).handleSubmit({
    preventDefault: vi.fn(),
  } as never);

  expect(createInterview).toHaveBeenCalledWith(
    'Study liver fibrosis',
    expect.any(Function),
    'sbi_ucd',
  );
});

test('posts no turn once a run has started', async () => {
  // The started session is the state the start round trip actually writes;
  // the composer is disabled in the UI and this guard keeps the handler
  // aligned with it, so nothing reaches the completed interview.
  vi.clearAllMocks();
  const deps = makeDeps({
    input: 'one more thing',
    interview: makeInterview({status: 'completed'}),
    startedSession: {id: 'run-1', title: 'Started', at: 1},
  });

  await buildChatHandlers(deps).handleSubmit({
    preventDefault: vi.fn(),
  } as never);

  expect(addInterviewTurn).not.toHaveBeenCalled();
  expect(createInterview).not.toHaveBeenCalled();
  expect(deps.setMessages).not.toHaveBeenCalled();
  expect(deps.setInput).not.toHaveBeenCalled();
});

test('stages only a completed persisted interview derivation', async () => {
  const active = makeInterview();
  const completed = makeInterview({
    status: 'completed',
    fields: {
      research_challenge: 'Study liver fibrosis',
      focus_area: ['Stellate-cell metabolism'],
      preferences: ['Human evidence'],
      title: 'Fibrosis metabolism',
    },
  });
  vi.mocked(addInterviewTurn).mockResolvedValue(completed);
  const deps = makeDeps({input: 'Focus on metabolism', interview: active});

  await buildChatHandlers(deps).handleSubmit({
    preventDefault: vi.fn(),
  } as never);

  expect(addInterviewTurn).toHaveBeenCalledWith(
    active.id,
    'Focus on metabolism',
    expect.any(Function),
  );
  expect(deps.stageDraftSpec).toHaveBeenCalledWith(
    expect.objectContaining({
      interviewId: active.id,
      goal: 'Study liver fibrosis',
      attributes: ['Stellate-cell metabolism'],
      requirements: ['Human evidence'],
    }),
    expect.any(Number),
    // The Agent's closing message is folded into the plan card as its intro,
    // not appended as a separate assistant bubble; its chain of thought rides
    // along so the completing turn keeps its thinking, and so does its turn
    // id, which is what the card's retry re-derives the plan from.
    {
      message: 'Which mechanisms should I prioritize?',
      reasoning: undefined,
      turnId: 1,
    },
  );
  // Twice: the optimistic bubble for the prompt just sent, then the rebuild
  // from the interview the server returned.
  expect(deps.setMessages).toHaveBeenCalledTimes(2);
});

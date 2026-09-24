// Reopening (or hard-refreshing) a chat whose run has answered questions
// must show those exchanges -- an answer that only ever lived in memory is
// worse than no answer. See use_chat_rehydrate.ts's third effect.

import {screen, within} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  apiMock,
  installChatWorkspaceMocks,
  minimalRun,
  renderWorkspace,
} from './chat_workspace_test_helpers';

const pendingIntentMock = vi.hoisted(() => vi.fn());

vi.mock('../hooks/chat_session_create_intent', async importOriginal => ({
  ...(await importOriginal<
    typeof import('../hooks/chat_session_create_intent')
  >()),
  readPendingCreateIntent: pendingIntentMock,
}));

beforeEach(() => {
  installChatWorkspaceMocks();
  pendingIntentMock.mockReset();
  pendingIntentMock.mockResolvedValue(undefined);
});

function completedInterview() {
  return {
    id: 'interview-1',
    client_id: 'client-1',
    status: 'completed' as const,
    fields: {
      research_challenge: 'Investigate glucose homeostasis.',
      focus_area: ['Cold-stress glucose regulation'],
      preferences: ['Prioritize mechanistic novelty'],
      title: 'Cold-stress glucose homeostasis',
    },
    current_question: null,
    turns: [
      {
        id: 1,
        role: 'user' as const,
        content: 'Investigate glucose homeostasis.',
        reasoning: null,
        fallback: false,
        created_at: 1,
      },
      {
        id: 2,
        role: 'agent' as const,
        content: 'I have enough detail to configure this research run.',
        reasoning: null,
        fallback: false,
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: 2,
  };
}

it('shows a run Q&A exchange after reopening the chat', async () => {
  apiMock.getInterview.mockResolvedValue(completedInterview());
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-1',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([minimalRun({id: 'run-1'})]);
  apiMock.getRunMessages.mockResolvedValue([
    {
      id: 10,
      run_id: 'run-1',
      sender: 'user',
      content: 'Which hypothesis ranked highest?',
      kind: 'qa',
      created_at: 10,
      applied: true,
      meta: null,
    },
    {
      id: 11,
      run_id: 'run-1',
      sender: 'system',
      content: 'The mitochondrial feedback hypothesis, at Elo 1240.',
      kind: 'qa',
      created_at: 11,
      applied: true,
      meta: {sources: []},
    },
    // A steering message on the same run must not be mistaken for Q&A.
    {
      id: 12,
      run_id: 'run-1',
      sender: 'user',
      content: 'Focus more on the cold-stress pathway.',
      kind: 'steering',
      created_at: 12,
      applied: false,
      meta: null,
    },
  ]);

  renderWorkspace('/chats/interview-1');

  expect(
    await screen.findByText('Which hypothesis ranked highest?'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('The mitochondrial feedback hypothesis, at Elo 1240.'),
  ).toBeInTheDocument();
  expect(
    screen.queryByText('Focus more on the cold-stress pathway.'),
  ).not.toBeInTheDocument();
});

it('shows the reasoning a rehydrated Q&A answer persisted', async () => {
  apiMock.getInterview.mockResolvedValue(completedInterview());
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-1',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([minimalRun({id: 'run-1'})]);
  apiMock.getRunMessages.mockResolvedValue([
    {
      id: 20,
      run_id: 'run-1',
      sender: 'user',
      content: 'Why does that hypothesis rank highest?',
      kind: 'qa',
      created_at: 20,
      applied: true,
      meta: null,
    },
    {
      id: 21,
      run_id: 'run-1',
      sender: 'system',
      content: 'Its Elo rating leads because it won every match.',
      kind: 'qa',
      created_at: 21,
      applied: true,
      meta: {reasoning: 'Checking the tournament record first.'},
    },
  ]);

  renderWorkspace('/chats/interview-1');

  expect(
    await screen.findByText('Its Elo rating leads because it won every match.'),
  ).toBeInTheDocument();
  expect(screen.getByText('Thinking')).toBeInTheDocument();
  expect(
    screen.getByText('Checking the tournament record first.'),
  ).toBeInTheDocument();
});

// The chat's opening exchange -- the scientist's "Start research" and the
// Agent's reply to it -- reopens the same way its questions do, and the
// session card carries that reply as its lead-in rather than a canned
// notice. The local-only bubble this replaced vanished on every reload.
it('restores the start exchange onto the session card', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-1',
  });
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-1',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({id: 'run-1', status: 'running'}),
  ]);
  apiMock.getRunMessages.mockResolvedValue([
    {
      id: 8,
      run_id: 'run-1',
      sender: 'user',
      content: 'Start research',
      kind: 'start',
      created_at: 8,
      applied: false,
      meta: null,
    },
    {
      id: 9,
      run_id: 'run-1',
      sender: 'system',
      content: 'Cold-stress glucose work is under way.',
      kind: 'start',
      created_at: 9,
      applied: false,
      meta: {reasoning: 'The run exists, so this confirms it.'},
    },
  ]);

  renderWorkspace('/chats/interview-1');

  // Wait for the reply, not just for the card: the card is built from the
  // chats and runs lists, and its lead-in arrives from a later, independent
  // fetch of the run's messages. Waiting on the card alone reads it while it
  // is still showing its standby copy.
  await screen.findByText('Cold-stress glucose work is under way.');
  const card = screen.getByRole('region', {
    name: 'Started research session',
  });
  expect(
    within(card).getByText('Cold-stress glucose work is under way.'),
  ).toBeInTheDocument();
  // The reply is the card's lead-in, not a bubble beside it, and the
  // scientist's own prompt is a bubble outside the card.
  expect(within(card).queryByText('Start research')).not.toBeInTheDocument();
  // The bubble, not the plan card's own Start control, which carries the
  // same words.
  const prompt = screen
    .getAllByText('Start research')
    .find(node => node.closest('button') === null);
  expect(prompt).toBeDefined();
  // The card is re-anchored to the reply it carries, so it sorts below the
  // prompt rather than at the run's earlier creation time.
  expect(
    prompt!.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.getByText('Thinking')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', {name: 'Continue research'}),
  ).not.toBeInTheDocument();
});

it('keeps a linked draft recoverable without treating it as started', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-1',
  });
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-1',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({id: 'run-1', status: 'draft'}),
  ]);

  renderWorkspace('/chats/interview-1');

  expect(
    await screen.findByRole('button', {name: 'Continue research'}),
  ).toBeEnabled();
  expect(
    screen.queryByRole('region', {name: 'Started research session'}),
  ).not.toBeInTheDocument();
  expect(apiMock.startRun).not.toHaveBeenCalled();
});

it('shows the linked draft run setup and pending notification before continuing', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-configured',
  });
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-configured',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({
      id: 'run-configured',
      status: 'draft',
      research_goal: 'Persisted run goal.',
      config: {
        focus: 'prefer_novelty',
        tier: 'ultra',
        setup: {
          goal: 'Persisted run goal.',
          requirements: ['Persisted requirement.'],
          attributes: [
            {name: 'Cell system', values: ['Organoid', 'Isogenic control']},
          ],
          criteria: [{name: 'Validation', value: 'Required'}],
          focus: 'prefer_novelty',
          tier: 'ultra',
        },
      },
    }),
  ]);
  pendingIntentMock.mockResolvedValue({
    key: 'saved-create-key',
    payload: {
      notify_on_completion: true,
      completion_email: 'saved@example.test',
    },
    createdRunId: 'run-configured',
  });

  renderWorkspace('/chats/interview-1');

  expect(
    await screen.findByRole('button', {name: 'Continue research'}),
  ).toBeEnabled();
  expect(screen.getByText('Persisted run goal.')).toBeInTheDocument();
  expect(screen.getByText('Persisted requirement.')).toBeInTheDocument();
  expect(
    screen.getByText('Cell system (Organoid or Isogenic control)'),
  ).toBeInTheDocument();
  expect(screen.getByText('Validation: Required')).toBeInTheDocument();
  expect(screen.getByLabelText(/Prefer novelty/i)).toBeChecked();
  expect(screen.getByLabelText(/Ultra/i)).toBeChecked();
  expect(
    screen.getByLabelText('Email me when the Goal Report is ready'),
  ).toHaveValue('saved@example.test');
  expect(pendingIntentMock).toHaveBeenCalledWith('interview-1');
  expect(apiMock.startRun).not.toHaveBeenCalled();
});

it('checks an owned run directly when run history has not loaded it', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-2',
  });
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-2',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([]);
  apiMock.getRun.mockResolvedValue(minimalRun({id: 'run-2', status: 'draft'}));

  renderWorkspace('/chats/interview-1');

  expect(
    await screen.findByRole('button', {name: 'Continue research'}),
  ).toBeEnabled();
  expect(apiMock.getRun).toHaveBeenCalledWith('run-2');
  expect(apiMock.startRun).not.toHaveBeenCalled();
});

it('keeps a linked run locked when its owned status cannot be resolved', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-3',
  });
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-3',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([]);
  apiMock.getRun.mockRejectedValueOnce(new Error('not found'));

  renderWorkspace('/chats/interview-1');

  const plan = await screen.findByRole('region', {name: 'Inferred run setup'});
  expect(await screen.findByRole('alert')).toHaveTextContent(
    /could not verify the saved run/i,
  );
  expect(
    screen.queryByRole('button', {name: 'Continue research'}),
  ).not.toBeInTheDocument();
  expect(
    within(plan).getByRole('button', {name: 'Start research'}),
  ).toBeDisabled();
  const retryStatus = within(plan).getByRole('button', {
    name: 'Retry status check',
  });
  apiMock.getRun.mockResolvedValueOnce(
    minimalRun({id: 'run-3', status: 'draft'}),
  );
  vi.mocked(pendingIntentMock).mockResolvedValueOnce(undefined);
  const lookupsBeforeRetry = apiMock.getRun.mock.calls.length;
  retryStatus.click();
  expect(
    await screen.findByRole('button', {name: 'Continue research'}),
  ).toBeEnabled();
  expect(apiMock.getRun.mock.calls.length).toBeGreaterThan(lookupsBeforeRetry);
  expect(apiMock.startRun).not.toHaveBeenCalled();
});

it('does not present a cancelled linked run as started or recoverable', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-cancelled',
  });
  apiMock.listInterviews.mockResolvedValue([
    {
      id: 'interview-1',
      title: 'Cold-stress glucose homeostasis',
      challenge: 'Investigate glucose homeostasis.',
      status: 'completed',
      run_id: 'run-cancelled',
      created_at: 1,
      updated_at: 3,
    },
  ]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({id: 'run-cancelled', status: 'cancelled'}),
  ]);

  renderWorkspace('/chats/interview-1');

  expect(
    await screen.findByText('The linked research session was cancelled.'),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('region', {name: 'Started research session'}),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', {name: 'Continue research'}),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Start research'})).toBeDisabled();
});

// Reopening (or hard-refreshing) a chat whose run has answered questions
// must show those exchanges -- an answer that only ever lived in memory is
// worse than no answer. See use_chat_rehydrate.ts's third effect.

import {screen, within} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {
  apiMock,
  installChatWorkspaceMocks,
  minimalRun,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
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

// The chat's opening exchange -- the scientist's "Start research" and the
// Agent's reply to it -- reopens the same way its questions do, and the
// session card carries that reply as its lead-in rather than a canned
// notice. The local-only bubble this replaced vanished on every reload.
it('restores the start exchange onto the session card', async () => {
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

  const card = await screen.findByRole('region', {
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
});

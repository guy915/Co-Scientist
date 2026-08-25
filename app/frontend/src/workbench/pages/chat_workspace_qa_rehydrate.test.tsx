// Reopening (or hard-refreshing) a chat whose run has answered questions
// must show those exchanges -- an answer that only ever lived in memory is
// worse than no answer. See use_chat_rehydrate.ts's third effect.

import {screen} from '@testing-library/react';
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

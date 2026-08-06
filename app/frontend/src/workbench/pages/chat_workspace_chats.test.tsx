import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {type Interview} from '@/api/runs';
import {
  apiMock,
  installChatWorkspaceMocks,
  renderWorkspace,
} from './chat_workspace_test_helpers';

beforeEach(() => {
  installChatWorkspaceMocks();
});

// A two-turn chat still in progress, with the Agent's reasoning stored on
// its turn the way the backend now persists it.
function activeInterview(): Interview {
  return {
    id: 'interview-7',
    client_id: 'client-1',
    status: 'active',
    documents: [],
    fields: {
      research_challenge: 'Study liver fibrosis',
      focus_area: [],
      preferences: [],
      title: null,
    },
    current_question: 'Which mechanisms should I prioritize?',
    turns: [
      {
        id: 1,
        role: 'user',
        content: 'Study liver fibrosis',
        reasoning: null,
        fallback: false,
        created_at: 1,
      },
      {
        id: 2,
        role: 'agent',
        content: 'Which mechanisms should I prioritize?',
        reasoning: 'No mechanism named yet, so ask for one.',
        fallback: false,
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: null,
  };
}

it('lists a chat and routes to it as soon as the first turn lands', async () => {
  renderWorkspace();

  const input = screen.getByRole('textbox');
  fireEvent.change(input, {target: {value: 'Study liver fibrosis'}});
  fireEvent.submit(input.closest('form')!);

  // The chat exists server-side from its first turn, so the URL names it and
  // the rail is told to reload -- both are what make it reopenable at all.
  await waitFor(() => {
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/chats/interview-1',
    );
  });
  expect(apiMock.listInterviews).toHaveBeenCalled();
});

it('reopens a chat from its id with the transcript and its thinking', async () => {
  const interview = activeInterview();
  apiMock.getInterview.mockResolvedValue(interview);

  renderWorkspace('/chats/interview-7');

  expect(await screen.findByText('Study liver fibrosis')).toBeInTheDocument();
  expect(
    screen.getByText('Which mechanisms should I prioritize?'),
  ).toBeInTheDocument();
  // The turn's chain of thought is kept with it rather than dropped when the
  // reply lands, so a reopened chat can still show why it asked.
  expect(screen.getByText('Thinking')).toBeInTheDocument();
  expect(
    screen.getByText('No mechanism named yet, so ask for one.'),
  ).toBeInTheDocument();
  expect(apiMock.getInterview).toHaveBeenCalledWith('interview-7');
});

import {makeChatSummary, makeRunMessage} from '@/test_fixtures';

import {act, renderHook, screen, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  apiMock,
  installChatWorkspaceMocks,
  minimalRun,
  renderWorkspace,
} from './chat_workspace_test_helpers';
import {
  RunHistoryProvider,
  ChatHistoryProvider,
} from '../hooks/history_context';
import {useChatSession} from '../hooks/use_chat_session';
import {useChatRehydration} from '../hooks/use_chat_rehydrate';

const pendingIntentMock = vi.hoisted(() => vi.fn());

vi.mock('../hooks/chat_session_start_run', async importOriginal => ({
  ...(await importOriginal<typeof import('../hooks/chat_session_start_run')>()),
  readPendingCreateIntent: pendingIntentMock,
}));

beforeEach(() => {
  installChatWorkspaceMocks();
  vi.clearAllMocks();
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => {
    resolve = done;
  });
  return {promise, resolve};
}

function rehydrateSession(chatId: string) {
  return renderHook(
    ({id}) => {
      const session = useChatSession({
        reloadHistory: async () => undefined,
        onChatStarted: () => undefined,
        focusComposer: () => undefined,
        setToast: () => undefined,
        pubmedEnabled: true,
        webSearchEnabled: true,
      });
      useChatRehydration(session, id);
      return session;
    },
    {
      initialProps: {id: chatId},
      reactStrictMode: true,
      wrapper: ({children}) => (
        <MemoryRouter>
          <RunHistoryProvider>
            <ChatHistoryProvider>{children}</ChatHistoryProvider>
          </RunHistoryProvider>
        </MemoryRouter>
      ),
    },
  );
}

it('adopts the second StrictMode transcript load before appending Q&A and ignores the cancelled first load', async () => {
  const cancelled = deferred<ReturnType<typeof completedInterview>>();
  const owned = deferred<ReturnType<typeof completedInterview>>();
  const rows = deferred<unknown[]>();
  apiMock.getInterview
    .mockReset()
    .mockReturnValueOnce(cancelled.promise)
    .mockReturnValueOnce(owned.promise);
  apiMock.getRunMessages.mockReset().mockReturnValue(rows.promise);
  apiMock.listInterviews.mockResolvedValue([
    makeChatSummary({run_id: 'run-1'}),
  ]);
  apiMock.listRuns.mockResolvedValue([minimalRun({id: 'run-1'})]);
  const {result} = rehydrateSession('interview-1');
  await waitFor(() => expect(apiMock.getInterview).toHaveBeenCalledTimes(2));
  expect(apiMock.getRunMessages).not.toHaveBeenCalled();
  await act(async () => {
    owned.resolve(completedInterview());
  });
  await waitFor(() =>
    expect(apiMock.getRunMessages).toHaveBeenCalledWith('run-1'),
  );
  await act(async () => {
    rows.resolve([
      makeRunMessage({
        id: 11,
        sender: 'system',
        content: 'Owned Q&A answer',
        created_at: 11,
        applied: true,
        meta: {reasoning: 'Owned evidence'},
      }),
    ]);
  });
  expect(result.current.messages.map(message => message.content)).toEqual([
    'Investigate glucose homeostasis.',
    'Owned Q&A answer',
  ]);
  expect(result.current.messages.at(-1)?.reasoning).toBe('Owned evidence');
  await act(async () => {
    cancelled.resolve({
      ...completedInterview(),
      turns: [
        {
          ...completedInterview().turns[0],
          content: 'Cancelled private transcript',
        },
      ],
    });
  });
  expect(result.current.messages.map(message => message.content)).toEqual([
    'Investigate glucose homeostasis.',
    'Owned Q&A answer',
  ]);
});

it('ignores an old owned fetch after another chat has committed', async () => {
  const old = deferred<ReturnType<typeof completedInterview>>();
  const next = {
    ...completedInterview(),
    id: 'interview-2',
    turns: [
      {...completedInterview().turns[0], content: 'Current private transcript'},
      completedInterview().turns[1],
    ],
  };
  apiMock.getInterview
    .mockReset()
    .mockImplementation(id =>
      id === 'interview-1' ? old.promise : Promise.resolve(next),
    );
  const {result, rerender} = rehydrateSession('interview-1');
  rerender({id: 'interview-2'});
  await waitFor(() => expect(result.current.interview?.id).toBe('interview-2'));
  await act(async () => {
    old.resolve({
      ...completedInterview(),
      turns: [
        {...completedInterview().turns[0], content: 'Old private transcript'},
      ],
    });
  });
  expect(result.current.interview?.id).toBe('interview-2');
  expect(result.current.messages.map(message => message.content)).toEqual([
    'Current private transcript',
  ]);
});

it('leaves an inaccessible interview empty under StrictMode', async () => {
  apiMock.getInterview
    .mockReset()
    .mockRejectedValue(new Error('404 not found'));
  const {result} = rehydrateSession('inaccessible-chat');
  await waitFor(() => expect(apiMock.getInterview).toHaveBeenCalledTimes(2));
  expect(result.current.interview).toBeNull();
  expect(result.current.messages).toEqual([]);
  expect(result.current.hasConversation).toBe(false);
});

it('shows a run Q&A exchange after reopening the chat', async () => {
  apiMock.getInterview.mockResolvedValue(completedInterview());
  apiMock.listInterviews.mockResolvedValue([makeChatSummary()]);
  apiMock.listRuns.mockResolvedValue([minimalRun({id: 'run-1'})]);
  apiMock.getRunMessages.mockResolvedValue([
    makeRunMessage({
      id: 10,
      content: 'Which hypothesis ranked highest?',
      created_at: 10,
      applied: true,
    }),
    makeRunMessage({
      id: 11,
      sender: 'system',
      content: 'The mitochondrial feedback hypothesis, at Elo 1240.',
      created_at: 11,
      applied: true,
      meta: {sources: []},
    }),
    makeRunMessage({
      id: 12,
      content: 'Focus more on the cold-stress pathway.',
      kind: 'steering',
      created_at: 12,
    }),
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
  apiMock.listInterviews.mockResolvedValue([makeChatSummary()]);
  apiMock.listRuns.mockResolvedValue([minimalRun({id: 'run-1'})]);
  apiMock.getRunMessages.mockResolvedValue([
    makeRunMessage({
      id: 20,
      content: 'Why does that hypothesis rank highest?',
      created_at: 20,
      applied: true,
    }),
    makeRunMessage({
      id: 21,
      sender: 'system',
      content: 'Its Elo rating leads because it won every match.',
      created_at: 21,
      applied: true,
      meta: {reasoning: 'Checking the tournament record first.'},
    }),
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

it('restores the start exchange onto the session card', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-1',
  });
  apiMock.listInterviews.mockResolvedValue([makeChatSummary()]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({id: 'run-1', status: 'running'}),
  ]);
  apiMock.getRunMessages.mockResolvedValue([
    makeRunMessage({
      id: 8,
      content: 'Start research',
      kind: 'start',
      created_at: 8,
    }),
    makeRunMessage({
      id: 9,
      sender: 'system',
      content: 'Cold-stress glucose work is under way.',
      kind: 'start',
      created_at: 9,
      meta: {reasoning: 'The run exists, so this confirms it.'},
    }),
  ]);

  renderWorkspace('/chats/interview-1');

  // The card and its lead-in arrive from independent requests; wait for the
  // reply.
  await screen.findByText('Cold-stress glucose work is under way.');
  const card = screen.getByRole('region', {
    name: 'Started research session',
  });
  expect(
    within(card).getByText('Cold-stress glucose work is under way.'),
  ).toBeInTheDocument();
  expect(within(card).queryByText('Start research')).not.toBeInTheDocument();
  const prompt = screen
    .getAllByText('Start research')
    .find(node => node.closest('button') === null);
  expect(prompt).toBeDefined();
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
  apiMock.listInterviews.mockResolvedValue([makeChatSummary()]);
  apiMock.listRuns.mockResolvedValue([
    minimalRun({id: 'run-1', status: 'draft'}),
  ]);

  renderWorkspace('/chats/interview-1');

  const resume = await screen.findByRole('button', {name: 'Continue research'});
  expect(resume).toBeEnabled();
  expect(
    screen.queryByRole('region', {name: 'Started research session'}),
  ).not.toBeInTheDocument();
  expect(apiMock.startRun).not.toHaveBeenCalled();

  apiMock.getRun.mockResolvedValue(minimalRun({id: 'run-1', status: 'draft'}));
  resume.click();

  await waitFor(() => expect(apiMock.startRun).toHaveBeenCalledWith('run-1'));
});

it('shows the linked draft run setup and pending notification before continuing', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-configured',
  });
  apiMock.listInterviews.mockResolvedValue([
    makeChatSummary({run_id: 'run-configured'}),
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
    makeChatSummary({run_id: 'run-2'}),
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
    makeChatSummary({run_id: 'run-3'}),
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
    makeChatSummary({run_id: 'run-cancelled'}),
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

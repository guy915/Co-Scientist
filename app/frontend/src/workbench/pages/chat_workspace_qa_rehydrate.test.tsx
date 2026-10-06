import {makeChatSummary} from '@/test_fixtures';

import {
  act,
  fireEvent,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
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

it('keeps a linked draft recoverable without treating it as started', async () => {
  apiMock.getInterview.mockResolvedValue({
    ...completedInterview(),
    run_id: 'run-1',
  });
  apiMock.listInterviews.mockResolvedValue([makeChatSummary()]);
  // The linked-run lookup falls back to getRun until run history loads; without
  // this mock it rejects first and the button only appears on the later,
  // history-triggered lookup, whose timing depends on machine load.
  const draft = minimalRun({id: 'run-1', status: 'draft'});
  apiMock.getRun.mockResolvedValue(draft);
  apiMock.listRuns.mockResolvedValue([draft]);

  renderWorkspace('/chats/interview-1');

  expect(
    await screen.findByRole('button', {name: 'Continue research'}),
  ).toBeEnabled();
  expect(
    screen.queryByRole('region', {name: 'Started research session'}),
  ).not.toBeInTheDocument();
  expect(apiMock.startRun).not.toHaveBeenCalled();

  // Each history update re-resolves the linked run and remounts the button, so
  // click a freshly found one rather than a node captured before the remount.
  fireEvent.click(
    await screen.findByRole('button', {name: 'Continue research'}),
  );

  await waitFor(() => expect(apiMock.startRun).toHaveBeenCalledWith('run-1'));
});

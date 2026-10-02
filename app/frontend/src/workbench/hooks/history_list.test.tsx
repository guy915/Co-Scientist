import {act, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter, useNavigate} from 'react-router-dom';
import {StrictMode, type ReactNode} from 'react';
import {beforeEach, expect, it, vi, type MockedFunction} from 'vitest';
import {listInterviews, loadRunHistory, type ChatSummary} from '@/api/runs';
import {makeRun} from '@/test_fixtures';
import {CHATS_CHANGED_EVENT, RUNS_CHANGED_EVENT} from '../dom_events';
import {
  ChatHistoryProvider,
  useChatHistoryContext,
} from './chat_history_context';
import {RunHistoryProvider, useRunHistoryContext} from './run_history_context';

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {...actual, listInterviews: vi.fn(), loadRunHistory: vi.fn()};
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(settle => {
    resolve = settle;
  });
  return {promise, resolve};
}

const chat = (id: string): ChatSummary => ({
  id,
  title: id,
  challenge: id,
  status: 'active',
  run_id: null,
  created_at: 1,
  updated_at: 1,
});

let reloadCurrent: () => Promise<void>;

function RunProbe() {
  const {history, reload} = useRunHistoryContext();
  reloadCurrent = reload;
  return <span data-testid="rows">{history.map(row => row.id).join(',')}</span>;
}

function ChatProbe() {
  const {chats, reload} = useChatHistoryContext();
  reloadCurrent = reload;
  return <span data-testid="rows">{chats.map(row => row.id).join(',')}</span>;
}

function Navigate() {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/other')}>Navigate</button>;
}

function renderHistory(
  provider: (props: {children: ReactNode}) => ReactNode,
  probe: ReactNode,
  strict = false,
) {
  const Provider = provider;
  const content = (
    <MemoryRouter>
      <Provider>
        {probe}
        <Navigate />
      </Provider>
    </MemoryRouter>
  );
  return render(strict ? <StrictMode>{content}</StrictMode> : content);
}

interface HistoryFixture<T> {
  name: string;
  provider: (props: {children: ReactNode}) => ReactNode;
  probe: ReactNode;
  event: string;
  load: MockedFunction<() => Promise<T[]>>;
  row: (id: string) => T;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(loadRunHistory).mockResolvedValue([]);
  vi.mocked(listInterviews).mockResolvedValue([]);
});

function historyContract<T>(history: HistoryFixture<T>) {
  it(`keeps newer ${history.name} history when an earlier load finishes later`, async () => {
    const older = deferred<T[]>();
    history.load.mockReturnValueOnce(older.promise);
    renderHistory(history.provider, history.probe);
    history.load.mockResolvedValue([history.row('newer')]);
    act(() => {
      window.dispatchEvent(new Event(history.event));
    });
    await waitFor(() =>
      expect(screen.getByTestId('rows')).toHaveTextContent('newer'),
    );
    await act(async () => older.resolve([history.row('older')]));
    expect(screen.getByTestId('rows')).toHaveTextContent('newer');
  });

  it(`reloads ${history.name} history once on navigation and removes its listener on unmount`, async () => {
    history.load.mockResolvedValue([history.row('first')]);
    const {unmount} = renderHistory(history.provider, history.probe);
    await waitFor(() =>
      expect(screen.getByTestId('rows')).toHaveTextContent('first'),
    );
    history.load.mockResolvedValue([history.row('next')]);
    act(() => screen.getByRole('button', {name: 'Navigate'}).click());
    await waitFor(() =>
      expect(screen.getByTestId('rows')).toHaveTextContent('next'),
    );
    expect(history.load).toHaveBeenCalledTimes(2);

    const retiredReload = reloadCurrent;
    unmount();
    await act(async () => {
      window.dispatchEvent(new Event(history.event));
      await retiredReload();
    });
    expect(history.load).toHaveBeenCalledTimes(2);
  });

  it(`retires the first ${history.name} load during StrictMode effect replay`, async () => {
    const retired = deferred<T[]>();
    history.load.mockReturnValueOnce(retired.promise);
    history.load.mockResolvedValue([history.row('current')]);
    renderHistory(history.provider, history.probe, true);
    await waitFor(() =>
      expect(screen.getByTestId('rows')).toHaveTextContent('current'),
    );
    await act(async () => retired.resolve([history.row('retired')]));
    expect(screen.getByTestId('rows')).toHaveTextContent('current');
  });
}

historyContract({
  name: 'run',
  provider: RunHistoryProvider,
  probe: <RunProbe />,
  event: RUNS_CHANGED_EVENT,
  load: vi.mocked(loadRunHistory),
  row: (id: string) => makeRun({id}),
});

historyContract({
  name: 'chat',
  provider: ChatHistoryProvider,
  probe: <ChatProbe />,
  event: CHATS_CHANGED_EVENT,
  load: vi.mocked(listInterviews),
  row: chat,
});

it('keeps chat history visible after a transient reload failure', async () => {
  vi.mocked(listInterviews).mockResolvedValue([chat('saved-chat')]);
  renderHistory(ChatHistoryProvider, <ChatProbe />);
  await waitFor(() =>
    expect(screen.getByTestId('rows')).toHaveTextContent('saved-chat'),
  );
  vi.mocked(listInterviews).mockRejectedValue(new Error('API unavailable'));
  await act(async () => reloadCurrent());
  expect(screen.getByTestId('rows')).toHaveTextContent('saved-chat');
});

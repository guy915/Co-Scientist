import {render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {makeRun} from '@/test_fixtures';
import {RunHistoryProvider, useRunHistoryContext} from './run_history_context';

vi.mock('@/api/runs', async () => {
  const actual =
    await vi.importActual<typeof import('@/api/runs')>('@/api/runs');
  return {...actual, loadRunHistory: vi.fn()};
});

const {loadRunHistory} = await import('@/api/runs');
const loadMock = vi.mocked(loadRunHistory);

function HistoryProbe() {
  const {history} = useRunHistoryContext();
  return <span data-testid="count">{history.length}</span>;
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <RunHistoryProvider>
        <HistoryProbe />
      </RunHistoryProvider>
    </MemoryRouter>,
  );
}

describe('RunHistoryProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers({shouldAdvanceTime: true});
    loadMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('refreshes on a timer while a run is still executing', async () => {
    // The recents step flow reads a run's live phase off this list, and no
    // navigation or run-start event fires as the run advances.
    loadMock.mockResolvedValue([makeRun({status: 'running'})]);
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('count')).toHaveTextContent('1'),
    );
    expect(loadMock).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(loadMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(loadMock).toHaveBeenCalledTimes(3);
  });

  it('stops refreshing once no run is executing', async () => {
    loadMock.mockResolvedValue([makeRun({status: 'completed'})]);
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('count')).toHaveTextContent('1'),
    );
    expect(loadMock).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(60_000);
    expect(loadMock).toHaveBeenCalledTimes(1);
  });

  it('stops refreshing after the executing run reaches a terminal status', async () => {
    loadMock.mockResolvedValue([makeRun({status: 'running'})]);
    renderProvider();
    await waitFor(() => expect(loadMock).toHaveBeenCalledTimes(1));

    loadMock.mockResolvedValue([makeRun({status: 'completed'})]);
    // Let the poll observe the terminal status and the timer tear down. A
    // refresh already in flight when the status turns terminal may still land,
    // so this asserts that polling settles rather than a call count.
    await vi.advanceTimersByTimeAsync(30_000);
    const callsOnceSettled = loadMock.mock.calls.length;

    await vi.advanceTimersByTimeAsync(60_000);
    expect(loadMock).toHaveBeenCalledTimes(callsOnceSettled);
  });
});

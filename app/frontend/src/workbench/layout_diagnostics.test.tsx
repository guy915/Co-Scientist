import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';
import {DIAGNOSTIC_EVENT} from './dom_events';

const copyMock = vi.hoisted(() => ({copyText: vi.fn()}));
vi.mock('@/lib/clipboard', () => copyMock);

const warningPayload = (lastId: number, sessionTotal: number) => ({
  logs: [],
  last_id: lastId,
  total: sessionTotal,
  session_total: sessionTotal,
});

const logsButton = () => screen.findByRole('button', {name: /^Logs/});
const dotOf = (button: HTMLElement) =>
  button.querySelector('[data-logged]')?.getAttribute('data-logged');

describe('logs button indicator', () => {
  beforeEach(() => {
    installLayoutMocks();
    copyMock.copyText.mockReset();
  });

  it('stays neutral when nothing was logged this session', async () => {
    renderLayout();
    const button = await logsButton();
    await waitFor(() => expect(logsApiMock.getAppLogs).toHaveBeenCalled());
    expect(dotOf(button)).toBe('false');
    expect(button).toHaveAccessibleDescription(
      'No warnings or errors logged this session',
    );
  });

  it('asks only for warnings after the session baseline', async () => {
    logsApiMock.getAppLogs.mockReset();
    logsApiMock.getAppLogs
      .mockResolvedValueOnce(warningPayload(100, 4))
      .mockResolvedValue(warningPayload(101, 1));
    renderLayout();
    await logsButton();
    await waitFor(() =>
      expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(0, 1, 'WARNING'),
    );

    fireEvent(window, new Event('cosci-app-logs-changed'));

    await waitFor(() =>
      expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(100, 1, 'WARNING'),
    );
    await waitFor(async () => expect(dotOf(await logsButton())).toBe('true'));
    expect(await logsButton()).toHaveAccessibleDescription(
      'A warning or error was logged this session',
    );
  });

  it('refreshes on visibility change but never on a timer', async () => {
    vi.useFakeTimers();
    try {
      renderLayout();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const initialCalls = logsApiMock.getAppLogs.mock.calls.length;

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(logsApiMock.getAppLogs).toHaveBeenCalledTimes(initialCalls);

      await act(async () => {
        document.dispatchEvent(new Event('visibilitychange'));
      });
      expect(logsApiMock.getAppLogs.mock.calls.length).toBeGreaterThan(
        initialCalls,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('ignores stale out-of-order responses', async () => {
    logsApiMock.getAppLogs.mockReset();
    logsApiMock.getAppLogs.mockResolvedValue(warningPayload(0, 0));
    renderLayout();
    const button = await logsButton();
    await waitFor(() => expect(logsApiMock.getAppLogs).toHaveBeenCalled());

    let resolveStale: (value: unknown) => void = () => {};
    logsApiMock.getAppLogs
      .mockReturnValueOnce(
        new Promise(resolve => {
          resolveStale = resolve;
        }),
      )
      .mockResolvedValue(warningPayload(0, 0));
    fireEvent(window, new Event('cosci-app-logs-changed'));
    fireEvent(window, new Event('cosci-app-logs-changed'));
    await act(async () => {
      resolveStale(warningPayload(5, 3));
    });

    expect(dotOf(button)).toBe('false');
  });
});

describe('logs button copy', () => {
  beforeEach(() => {
    installLayoutMocks();
    copyMock.copyText.mockReset();
  });

  it('copies the session export and confirms briefly', async () => {
    renderLayout();
    const button = await logsButton();

    fireEvent.click(button);

    await waitFor(() => expect(copyMock.copyText).toHaveBeenCalledTimes(1));
    expect(copyMock.copyText.mock.calls[0][0]).toContain('## Logs (JSON)');
    expect(await screen.findByText('Copied')).toBeInTheDocument();
    expect(button).toHaveAccessibleName('Logs — copy session logs');
    expect(screen.queryByRole('group', {name: /diagnostic logs/i})).toBeNull();
  });
});

describe('layout diagnostic events', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('never persists goal text as a run id', async () => {
    renderLayout();

    // Display titles must not be stored as run_id.
    fireEvent(
      window,
      new CustomEvent(DIAGNOSTIC_EVENT, {
        detail: {
          stage: 'LIFECYCLE',
          run: 'Novel oncology target X in pancreatic cancer',
          level: 'info',
          payload: {event: 'start_requested'},
        },
      }),
    );

    await waitFor(() => expect(logsApiMock.postAppLogs).toHaveBeenCalled());
    const posted = logsApiMock.postAppLogs.mock.calls
      .flatMap(call => call[0] as {message: string; run_id?: string}[])
      .filter(record => record.message.startsWith('LIFECYCLE'));
    expect(posted).toHaveLength(1);
    expect(posted[0].run_id).toBeUndefined();
    expect(JSON.stringify(posted[0])).not.toContain('oncology');
  });
});

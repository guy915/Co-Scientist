import {act, fireEvent, screen} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

beforeEach(() => {
  installLayoutMocks();
});

it('opens the logs popover and dismisses on outside click', async () => {
  renderLayout();

  fireEvent.click(screen.getByRole('button', {name: /Logs 0/i}));
  expect(screen.getByRole('button', {name: /Logs 0/i})).toHaveAttribute(
    'data-tooltip',
    'Logs',
  );
  expect(screen.getByText('Diagnostic Logs')).toBeInTheDocument();
  expect(screen.queryByText('All runs')).toBeNull();
  expect(screen.getByText('Total 0')).toBeInTheDocument();
  expect(screen.getByText('Errors 0')).toBeInTheDocument();
  expect(screen.getByText('Warnings 0')).toBeInTheDocument();
  expect(screen.getByText('Info 0')).toBeInTheDocument();
  expect(screen.getByText('No diagnostic events loaded.')).toBeInTheDocument();
  const diagnosticActions = document.querySelector('.ucs-diagnostic-actions');
  expect(diagnosticActions).not.toBeNull();
  expect(
    Array.from(diagnosticActions!.querySelectorAll('button')).map(button =>
      button.querySelector('span')?.textContent?.trim(),
    ),
  ).toEqual(['Clear', 'Copy']);

  fireEvent.pointerDown(screen.getByText('Workspace content'));
  expect(screen.queryByText('Diagnostic Logs')).toBeNull();
});

it('refreshes the badge when the api announces a log change', async () => {
  renderLayout();
  await screen.findByRole('button', {name: /Logs 0/i});

  // A client record was persisted somewhere (e.g. a button click was
  // logged): the api layer announces it and the badge updates without
  // the popover ever being opened.
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      {
        id: 7,
        created_at: 1_700_000_007,
        level: 'INFO',
        levelno: 20,
        logger: 'ui.interaction',
        message: 'click: "Start" (button)',
        run_id: null,
        exc_text: null,
      },
    ],
    last_id: 7,
    total: 7,
  });
  const {APP_LOGS_CHANGED_EVENT} = await import('@/api/logs');
  fireEvent(window, new Event(APP_LOGS_CHANGED_EVENT));

  expect(
    await screen.findByRole('button', {name: /Logs 7/i}),
  ).toBeInTheDocument();
});

it('keeps the badge fresh while the popover is closed', async () => {
  vi.useFakeTimers();
  try {
    renderLayout();
    // Flush the initial mount-time loads.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole('button', {name: /Logs 0/i})).toBeInTheDocument();

    logsApiMock.getAppLogs.mockResolvedValue({
      logs: [
        {
          id: 9,
          created_at: 1_700_000_009,
          level: 'INFO',
          levelno: 20,
          logger: 'app.main',
          message: 'run finished',
          run_id: null,
          exc_text: null,
        },
      ],
      last_id: 9,
      total: 9,
    });
    // No popover open, no events: only the periodic background poll
    // can pick up the new record.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(screen.getByRole('button', {name: /Logs 9/i})).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

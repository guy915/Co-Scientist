import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

beforeEach(() => installLayoutMocks());

it('clears the persisted log from the Clear action', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      {
        id: 1,
        created_at: 1_700_000_000,
        level: 'INFO',
        levelno: 20,
        logger: 'app.main',
        message: 'server started',
        run_id: null,
        exc_text: null,
      },
    ],
    last_id: 1,
    total: 1,
  });
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
  expect(await screen.findByText(/server started/)).toBeInTheDocument();

  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [],
    last_id: 1,
    total: 0,
  });
  fireEvent.click(screen.getByRole('button', {name: 'Clear'}));

  // Clear deletes server-side, not just in this tab's memory.
  await waitFor(() => expect(logsApiMock.deleteAppLogs).toHaveBeenCalled());
  expect(
    await screen.findByText('No diagnostic events loaded.'),
  ).toBeInTheDocument();
});

it('copies only the newest 50 entries', async () => {
  const many = Array.from({length: 60}, (_, index) => ({
    id: index + 1,
    created_at: 1_700_000_000 + index,
    level: 'INFO',
    levelno: 20,
    logger: 'app.main',
    message: `record ${index + 1}`,
    run_id: null,
    exc_text: null,
  }));
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: many,
    last_id: 60,
    total: 60,
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, {clipboard: {writeText}});
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 60/i}));
  // The full window loads when the popover opens; Copy reads it.
  await screen.findByText(/record 60/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

  await waitFor(() => expect(writeText).toHaveBeenCalled());
  const copied = JSON.parse(writeText.mock.calls[0][0] as string);
  expect(copied).toHaveLength(50);
  // The newest tail, not the oldest head.
  expect(copied[0].payload.message).toBe('record 11');
  expect(copied[49].payload.message).toBe('record 60');
});

it('copies the real store ids, not the display numbers', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [12, 30].map(id => ({
      id,
      created_at: 1_700_000_000 + id,
      level: 'INFO',
      levelno: 20,
      logger: 'app.main',
      message: `record ${id}`,
      run_id: null,
      exc_text: null,
    })),
    last_id: 33,
    total: 2,
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, {clipboard: {writeText}});
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
  // The full window loads when the popover opens; Copy reads it.
  await screen.findByText(/record 30/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

  await waitFor(() => expect(writeText).toHaveBeenCalled());
  const copied = JSON.parse(writeText.mock.calls[0][0] as string);
  // Copy stays cross-referenceable with `cosci logs` and after_id
  // cursors, which speak store ids.
  expect(copied.map((e: {id: number}) => e.id)).toEqual([12, 30]);
  expect(copied.map((e: {number: number}) => e.number)).toEqual([1, 2]);
});

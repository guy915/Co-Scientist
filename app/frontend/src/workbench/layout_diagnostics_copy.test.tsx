import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {COPY_LIMIT} from './layout_diagnostics_data';
import {EXPORT_LOGS_MARKER} from './layout_diagnostics_data';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

beforeEach(() => installLayoutMocks());
afterEach(() => vi.useRealTimers());

function copiedEntries(text: string): Record<string, unknown>[] {
  const json = text.slice(text.indexOf(EXPORT_LOGS_MARKER));
  return JSON.parse(json.slice(EXPORT_LOGS_MARKER.length)) as Record<
    string,
    unknown
  >[];
}

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
    session_total: 1,
  });
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
  expect(await screen.findByText(/server started/)).toBeInTheDocument();

  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [],
    last_id: 1,
    total: 0,
    session_total: 0,
  });
  fireEvent.click(screen.getByRole('button', {name: 'Clear'}));

  await waitFor(() => expect(logsApiMock.deleteAppLogs).toHaveBeenCalled());
  expect(
    await screen.findByText('No diagnostic events loaded.'),
  ).toBeInTheDocument();
});

it('copies the newest COPY_LIMIT entries, not the whole session', async () => {
  const many = Array.from({length: 140}, (_, index) => ({
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
    last_id: 140,
    total: 140,
    session_total: 140,
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, {clipboard: {writeText}});
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 140/i}));
  await screen.findByText(/record 140/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

  await waitFor(() => expect(writeText).toHaveBeenCalled());
  const copied = copiedEntries(writeText.mock.calls[0][0] as string) as {
    payload: {message: string};
  }[];
  expect(copied).toHaveLength(COPY_LIMIT);
  expect(copied[0].payload.message).toBe('record 41');
  expect(copied[COPY_LIMIT - 1].payload.message).toBe('record 140');
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
    session_total: 2,
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, {clipboard: {writeText}});
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 2/i}));
  await screen.findByText(/record 30/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

  await waitFor(() => expect(writeText).toHaveBeenCalled());
  const copied = copiedEntries(writeText.mock.calls[0][0] as string) as {
    id: number;
    number: number;
  }[];
  // Exports retain store ids for backend cursor cross-references.
  expect(copied.map(entry => entry.id)).toEqual([12, 30]);
  expect(copied.map(entry => entry.number)).toEqual([1, 2]);
});

function oneRecordPayload() {
  return {
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
    session_total: 1,
  };
}

it('prefixes the copied logs with an explanatory preamble', async () => {
  logsApiMock.getAppLogs.mockResolvedValue(oneRecordPayload());
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, {clipboard: {writeText}});
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
  await screen.findByText(/server started/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

  await waitFor(() => expect(writeText).toHaveBeenCalled());
  const text = writeText.mock.calls[0][0] as string;
  expect(text).toContain('=== ABOUT THESE DIAGNOSTIC LOGS ===');
  expect(text).toContain('=== WHAT THIS TRACKS ===');
  expect(text).toContain('=== SESSION DETAILS ===');
  expect(text).toContain('=== FIELD LEGEND ===');
  expect(text).toContain('Records this session: 1');
  expect(text).toContain('In this export: 1');
  expect(text.indexOf(EXPORT_LOGS_MARKER)).toBeGreaterThan(0);
  expect(copiedEntries(text)).toHaveLength(1);
});

it('returns the Copy button to "Copy" after the confirmation', async () => {
  // Keep real time for render awaits while manually driving only the copy
  // timeout.
  vi.useFakeTimers({shouldAdvanceTime: true});
  logsApiMock.getAppLogs.mockResolvedValue(oneRecordPayload());
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, {clipboard: {writeText}});
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
  await screen.findByText(/server started/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));
  expect(await screen.findByRole('button', {name: 'Copied'})).toBeTruthy();

  act(() => {
    vi.advanceTimersByTime(2_000);
  });
  expect(screen.getByRole('button', {name: 'Copy'})).toBeTruthy();
});

import {act, fireEvent, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {COPY_LIMIT} from './layout_diagnostics_data';
import {EXPORT_LOGS_MARKER} from './layout_diagnostics_export';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

beforeEach(() => installLayoutMocks());
afterEach(() => vi.useRealTimers());

// The clipboard payload is a context preamble followed by the entries as
// JSON under a marker line; tests assert on the parsed entries.
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

  // Clear deletes server-side, not just in this tab's memory.
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
  // The full window loads when the popover opens; Copy reads it.
  await screen.findByText(/record 140/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

  await waitFor(() => expect(writeText).toHaveBeenCalled());
  const copied = copiedEntries(writeText.mock.calls[0][0] as string) as {
    payload: {message: string};
  }[];
  expect(copied).toHaveLength(COPY_LIMIT);
  // The newest tail, not the oldest head.
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
  // The full window loads when the popover opens; Copy reads it.
  await screen.findByText(/record 30/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));

  await waitFor(() => expect(writeText).toHaveBeenCalled());
  const copied = copiedEntries(writeText.mock.calls[0][0] as string) as {
    id: number;
    number: number;
  }[];
  // Copy stays cross-referenceable with `cosci logs` and after_id
  // cursors, which speak store ids.
  expect(copied.map(entry => entry.id)).toEqual([12, 30]);
  expect(copied.map(entry => entry.number)).toEqual([1, 2]);
});

// One INFO record, enough to open the panel and copy from it.
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
  // A pasted export explains itself: what the log is, what it omits,
  // where it was taken, and how to read the two id columns.
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
  // Real time still advances, so the render's own awaits resolve; only
  // the "Copied" timeout is driven by hand.
  vi.useFakeTimers({shouldAdvanceTime: true});
  logsApiMock.getAppLogs.mockResolvedValue(oneRecordPayload());
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, {clipboard: {writeText}});
  renderLayout();

  fireEvent.click(await screen.findByRole('button', {name: /Logs 1/i}));
  await screen.findByText(/server started/);
  fireEvent.click(screen.getByRole('button', {name: 'Copy'}));
  expect(await screen.findByRole('button', {name: 'Copied'})).toBeTruthy();

  // "Copied" is confirmation, not a mode: the label expires on its own so
  // a second copy is never left guessing whether it took.
  act(() => {
    vi.advanceTimersByTime(2_000);
  });
  expect(screen.getByRole('button', {name: 'Copy'})).toBeTruthy();
});

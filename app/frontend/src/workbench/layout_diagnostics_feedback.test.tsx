import {makeLogRecord as logRecord} from '@/test_fixtures';
import {beforeEach, expect, it, vi} from 'vitest';
import {sessionDiagnosticExport} from './layout_diagnostics';
import {EXPORT_LOGS_MARKER} from './layout_diagnostics_data';
import {resetSessionBaselineForTest} from './layout_diagnostics';

const logsApiMock = vi.hoisted(() => ({getAppLogs: vi.fn()}));
vi.mock('@/api/logs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/logs')>()),
  ...logsApiMock,
}));

beforeEach(() => resetSessionBaselineForTest());

it('shares the existing session anchor and exports operational records with the complete preamble', async () => {
  window.sessionStorage.setItem(
    'cosci-logs-session-baseline',
    JSON.stringify({id: 10}),
  );
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [
      logRecord(9),
      logRecord(11, {
        logger: 'co_scientist.llm.tools',
        message: 'tool_call name=search duration_seconds=0.25',
      }),
    ],
    last_id: 11,
    total: 2,
    session_total: 1,
  });
  const text = await sessionDiagnosticExport();
  expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(10, 100, true);
  expect(text).toContain('=== ABOUT THESE DIAGNOSTIC LOGS ===');
  expect(text).toContain('=== SESSION DETAILS ===');
  expect(text).toContain('=== STATISTICS (loaded window) ===');
  const records = JSON.parse(text.split(EXPORT_LOGS_MARKER)[1]) as {
    id: number;
  }[];
  expect(records.map(record => record.id)).toEqual([11]);
  expect(text).toContain('tool_call name=search');
});

it('excludes pre-tab history when the baseline has not been initialized', async () => {
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [logRecord(2)],
    last_id: 2,
    total: 1,
    session_total: 1,
  });
  const text = await sessionDiagnosticExport();
  expect(JSON.parse(text.split(EXPORT_LOGS_MARKER)[1])).toEqual([]);
  expect(text).toContain('Records this session: 0');
});

it('bounds a multibyte diagnostic export without losing the preamble or newest record', async () => {
  window.sessionStorage.setItem(
    'cosci-logs-session-baseline',
    JSON.stringify({id: 0}),
  );
  const logs = Array.from({length: 100}, (_, i) =>
    logRecord(i + 1, {message: '界'.repeat(4000)}),
  );
  logsApiMock.getAppLogs.mockResolvedValue({
    logs,
    last_id: 100,
    total: 100,
    session_total: 100,
  });
  const text = await sessionDiagnosticExport();
  expect(text.length).toBeLessThanOrEqual(100_000);
  const records = JSON.parse(text.split(EXPORT_LOGS_MARKER)[1]) as {
    id: number;
  }[];
  expect(records.at(-1)?.id).toBe(100);
  expect(records.length).toBeLessThan(100);
  expect(text).toContain('Records this session: 100');
});

it('preserves a useful export when fetching diagnostics fails', async () => {
  logsApiMock.getAppLogs.mockRejectedValue(new Error('API unavailable'));
  const text = await sessionDiagnosticExport();
  expect(text).toContain('Session diagnostics were unavailable');
  expect(text).toContain('=== SESSION DETAILS ===');
  expect(JSON.parse(text.split(EXPORT_LOGS_MARKER)[1])).toHaveLength(1);
});

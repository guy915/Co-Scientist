import {exportedRecords, makeLogRecord as logRecord} from '@/test_fixtures';
import {beforeEach, expect, it, vi} from 'vitest';
import {sessionDiagnosticExport} from './layout_diagnostics';
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
  expect(text).toContain('## About these logs');
  expect(text).toContain('## Session details');
  expect(text).toContain('## Statistics (loaded window)');
  const records = exportedRecords<{id: number}>(text);
  expect(records.map(record => record.id)).toEqual([11]);
  expect(text).toContain('tool_call name=search');
});

it('preserves a useful export when fetching diagnostics fails', async () => {
  logsApiMock.getAppLogs.mockRejectedValue(new Error('API unavailable'));
  const text = await sessionDiagnosticExport();
  expect(text).toContain('Session diagnostics were unavailable');
  expect(text).toContain('## Session details');
  expect(exportedRecords<{id: number}>(text)).toHaveLength(1);
});

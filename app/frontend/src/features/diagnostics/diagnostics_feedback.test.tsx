import {exportedRecords} from '@/test_fixtures';
import {beforeEach, expect, it, vi} from 'vitest';
import {
  resetSessionBaselineForTest,
  sessionDiagnosticExport,
} from './diagnostics';

const logsApiMock = vi.hoisted(() => ({getAppLogs: vi.fn()}));
vi.mock('@/shared/api/logs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/shared/api/logs')>()),
  ...logsApiMock,
}));

beforeEach(() => resetSessionBaselineForTest());

it('preserves a useful export when fetching diagnostics fails', async () => {
  logsApiMock.getAppLogs.mockRejectedValue(new Error('API unavailable'));
  const text = await sessionDiagnosticExport();
  expect(text).toContain('Session diagnostics were unavailable');
  expect(text).toContain('## Session details');
  expect(exportedRecords<{id: number}>(text)).toHaveLength(1);
});

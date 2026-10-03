import {act, waitFor} from '@testing-library/react';
import {expect} from 'vitest';
import type {AppLogRecord} from '@/api/logs';
import {logsApiMock} from './layout_test_support';

export function logRecord(
  id: number,
  overrides: Partial<AppLogRecord> = {},
): AppLogRecord {
  return {
    id,
    created_at: 1_700_000_000 + id,
    level: 'INFO',
    levelno: 20,
    logger: 'app.main',
    message: `record ${id}`,
    run_id: null,
    exc_text: null,
    ...overrides,
  };
}

// jsdom performs no layout; stub the list's scroll geometry.
export function stubListGeometry(list: HTMLElement): void {
  Object.defineProperty(list, 'scrollHeight', {
    configurable: true,
    value: 1000,
  });
  Object.defineProperty(list, 'clientHeight', {
    configurable: true,
    value: 100,
  });
}

// Settle remount-time loads so racing requests share one effect generation, not
// disposal guards.
export async function settleMountTimeLoads(): Promise<void> {
  await waitFor(() =>
    expect(logsApiMock.getAppLogs.mock.calls.length).toBeGreaterThanOrEqual(2),
  );
  await act(async () => {
    // let the remounted effect finish its initial load
  });
}

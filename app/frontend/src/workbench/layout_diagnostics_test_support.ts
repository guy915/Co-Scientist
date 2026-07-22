import {act, waitFor} from '@testing-library/react';
import {expect} from 'vitest';
import type {AppLogRecord} from '@/api/logs';
import {logsApiMock} from './layout_test_support';

/** Builds an {@link AppLogRecord} with sane defaults for the given id. */
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

/** jsdom does no layout, so the list's scroll geometry is stubbed. */
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

/**
 * Waits for the mount-time log loads to settle — including the remount
 * caused by the navigation-log version bump — so racing requests issued
 * afterwards belong to the same effect generation (the `disposed` guard
 * must not be what saves us).
 */
export async function settleMountTimeLoads(): Promise<void> {
  await waitFor(() =>
    expect(logsApiMock.getAppLogs.mock.calls.length).toBeGreaterThanOrEqual(2),
  );
  await act(async () => {
    // let the remounted effect finish its initial load
  });
}

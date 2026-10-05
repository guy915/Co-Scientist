export {makeLogRecord as logRecord} from '@/test_fixtures';
import {act, waitFor} from '@testing-library/react';
import {expect} from 'vitest';
import {logsApiMock} from './layout_test_support';

// jsdom performs no layout; stub scroll geometry.
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

// Settle mount loads so race cases share one effect generation rather than
// disposal guards.
export async function settleMountTimeLoads(): Promise<void> {
  await waitFor(() =>
    expect(logsApiMock.getAppLogs.mock.calls.length).toBeGreaterThanOrEqual(2),
  );
  await act(async () => {
    // React's pending load effects finish only after another microtask.
  });
}

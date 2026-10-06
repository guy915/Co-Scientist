export {makeLogRecord as logRecord} from '@/test_fixtures';
import {act, waitFor} from '@testing-library/react';
import {expect} from 'vitest';
import {logsApiMock} from './layout_test_support';

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

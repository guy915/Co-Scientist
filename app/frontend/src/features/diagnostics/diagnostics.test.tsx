import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from '@/app/layout_test_support';
import {DIAGNOSTIC_EVENT} from '@/shared/lib/dom_events';

describe('session diagnostics', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('anchors the feedback export when the shell mounts', async () => {
    renderLayout();
    await waitFor(() =>
      expect(logsApiMock.getAppLogs).toHaveBeenCalledWith(0, 1, 'WARNING'),
    );
  });

  it('has no header Logs button', async () => {
    renderLayout();
    await waitFor(() => expect(logsApiMock.getAppLogs).toHaveBeenCalled());
    expect(screen.queryByRole('button', {name: /^Logs/})).toBeNull();
  });
});

describe('layout diagnostic events', () => {
  beforeEach(() => {
    installLayoutMocks();
  });

  it('never persists goal text as a run id', async () => {
    renderLayout();

    // Display titles must not be stored as run_id.
    fireEvent(
      window,
      new CustomEvent(DIAGNOSTIC_EVENT, {
        detail: {
          stage: 'LIFECYCLE',
          run: 'Novel oncology target X in pancreatic cancer',
          level: 'info',
          payload: {event: 'start_requested'},
        },
      }),
    );

    await waitFor(() => expect(logsApiMock.postAppLogs).toHaveBeenCalled());
    const posted = logsApiMock.postAppLogs.mock.calls
      .flatMap(call => call[0] as {message: string; run_id?: string}[])
      .filter(record => record.message.startsWith('LIFECYCLE'));
    expect(posted).toHaveLength(1);
    expect(posted[0].run_id).toBeUndefined();
    expect(JSON.stringify(posted[0])).not.toContain('oncology');
  });
});

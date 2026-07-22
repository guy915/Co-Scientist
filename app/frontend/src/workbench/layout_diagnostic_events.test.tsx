import {fireEvent, waitFor} from '@testing-library/react';
import {beforeEach, expect, it} from 'vitest';
import {DIAGNOSTIC_EVENT} from './dom_events';
import {
  installLayoutMocks,
  logsApiMock,
  renderLayout,
} from './layout_test_support';

beforeEach(() => {
  installLayoutMocks();
});

it('never persists goal text as a run id', async () => {
  renderLayout();

  // Callers used to pass a goal-derived title as `run`, which was
  // stored in the run_id column and served over the API. Only a real
  // run id may become run_id; a display title is ignored.
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

it('ships in-page diagnostic events to the persisted log', async () => {
  renderLayout();

  fireEvent(
    window,
    new CustomEvent(DIAGNOSTIC_EVENT, {
      detail: {
        stage: 'LIFECYCLE',
        runId: 'run-abc',
        level: 'info',
        payload: {event: 'draft_created'},
      },
    }),
  );

  // The event is POSTed to the app-wide log rather than kept in memory,
  // so it survives reloads and is visible to the CLI and other tabs.
  await waitFor(() =>
    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {
        message: 'LIFECYCLE {"event":"draft_created"}',
        level: 'info',
        logger: 'session',
        run_id: 'run-abc',
      },
    ]),
  );
});

it('persists route navigation into the log', async () => {
  renderLayout('/');

  await waitFor(() =>
    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'page loaded at /', logger: 'navigation'},
    ]),
  );
});

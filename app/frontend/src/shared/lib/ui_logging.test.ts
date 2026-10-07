import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {emitDiagnostic} from './diagnostic_events';
import {
  installDiagnosticLogging,
  installUiErrorLogging,
  installUiInteractionLogging,
  logUiError,
} from './ui_logging';

const logsApiMock = vi.hoisted(() => ({postAppLogs: vi.fn()}));

vi.mock('@/shared/api/logs', () => logsApiMock);

beforeEach(() => {
  logsApiMock.postAppLogs.mockReset();
  logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
});

describe('error logging', () => {
  it('persists uncaught errors', () => {
    const uninstall = installUiErrorLogging();
    window.dispatchEvent(
      new ErrorEvent('error', {
        message: 'boom',
        filename: 'app.js',
        lineno: 12,
      }),
    );

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {
        message: 'uncaught error: boom (app.js:12)',
        level: 'error',
        logger: 'error',
      },
    ]);
    uninstall();
  });

  it('stops persisting after uninstall', () => {
    const uninstall = installUiErrorLogging();
    uninstall();
    window.dispatchEvent(new ErrorEvent('error', {message: 'ignored'}));

    expect(logsApiMock.postAppLogs).not.toHaveBeenCalled();
  });

  it('never throws when the API is unreachable', async () => {
    logsApiMock.postAppLogs.mockRejectedValue(new Error('offline'));
    const uninstall = installUiErrorLogging();

    expect(() =>
      window.dispatchEvent(new ErrorEvent('error', {message: 'boom'})),
    ).not.toThrow();
    uninstall();
  });

  it('logs render errors with their component stack', () => {
    logUiError('render error: Error: bad render', 'at Component');

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {
        message: 'render error: Error: bad render | at Component',
        level: 'error',
        logger: 'error',
      },
    ]);
  });
});

describe('interaction logging', () => {
  let uninstall: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    uninstall = installUiInteractionLogging();
  });

  afterEach(() => {
    uninstall();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  function mount<T extends HTMLElement>(element: T): T {
    document.body.appendChild(element);
    return element;
  }

  it('persists clicks on buttons using their visible text', () => {
    const button = mount(document.createElement('button'));
    button.textContent = 'Start run';
    button.click();
    vi.runAllTimers();

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'click: "Start run" (button)', logger: 'interaction'},
    ]);
  });

  it('batches rapid interactions into one POST', () => {
    const button = mount(document.createElement('button'));
    button.textContent = 'Start run';
    button.click();
    button.click();
    expect(logsApiMock.postAppLogs).not.toHaveBeenCalled();
    vi.runAllTimers();

    expect(logsApiMock.postAppLogs).toHaveBeenCalledTimes(1);
    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'click: "Start run" (button)', logger: 'interaction'},
      {message: 'click: "Start run" (button)', logger: 'interaction'},
    ]);
  });

  it('flushes the buffer when the page hides', () => {
    const button = mount(document.createElement('button'));
    button.textContent = 'Start run';
    button.click();
    window.dispatchEvent(new Event('pagehide'));

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'click: "Start run" (button)', logger: 'interaction'},
    ]);
    vi.runAllTimers();
    expect(logsApiMock.postAppLogs).toHaveBeenCalledTimes(1);
  });
});

describe('diagnostic logging', () => {
  it('persists session diagnostics with no shell mounted', () => {
    const uninstall = installDiagnosticLogging();
    emitDiagnostic({
      stage: 'LIFECYCLE',
      runId: 'run-1',
      payload: {event: 'start_requested'},
    });
    uninstall();
    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {
        message: 'LIFECYCLE {"event":"start_requested"}',
        level: 'info',
        logger: 'session',
        run_id: 'run-1',
      },
    ]);
  });

  it('never persists goal text as a run id', () => {
    const uninstall = installDiagnosticLogging();
    window.dispatchEvent(
      new CustomEvent('cosci-diagnostic-event', {
        detail: {
          stage: 'LIFECYCLE',
          run: 'Novel oncology target X in pancreatic cancer',
          payload: {event: 'start_requested'},
        },
      }),
    );
    uninstall();
    const [records] = logsApiMock.postAppLogs.mock.calls[0] as [
      {run_id?: string}[],
    ];
    expect(records[0].run_id).toBeUndefined();
    expect(JSON.stringify(records)).not.toContain('oncology');
  });
});

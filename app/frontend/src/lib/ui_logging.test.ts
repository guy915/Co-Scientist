import {beforeEach, describe, expect, it, vi} from 'vitest';
import {installUiErrorLogging, logUiError} from './ui_logging';

const logsApiMock = vi.hoisted(() => ({postAppLogs: vi.fn()}));

vi.mock('@/api/logs', () => logsApiMock);

describe('ui error logging', () => {
  beforeEach(() => {
    logsApiMock.postAppLogs.mockReset();
    logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
  });

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

  it('persists unhandled promise rejections', () => {
    const uninstall = installUiErrorLogging();
    const event = new Event('unhandledrejection') as Event & {
      reason?: unknown;
    };
    event.reason = new Error('async boom');
    window.dispatchEvent(event);

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {
        message: 'unhandled rejection: Error: async boom',
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

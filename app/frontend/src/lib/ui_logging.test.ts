import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  installUiErrorLogging,
  installUiInteractionLogging,
  logUiError,
} from './ui_logging';

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

describe('ui interaction logging', () => {
  let uninstall: () => void;

  beforeEach(() => {
    logsApiMock.postAppLogs.mockReset();
    logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
    uninstall = installUiInteractionLogging();
  });

  afterEach(() => {
    uninstall();
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

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'click: "Start run" (button)', logger: 'interaction'},
    ]);
  });

  it('falls back to the aria-label for icon-only controls', () => {
    const button = mount(document.createElement('button'));
    button.setAttribute('aria-label', 'Menu');
    button.click();

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'click: "Menu" (button)', logger: 'interaction'},
    ]);
  });

  it('attributes clicks on children to the enclosing control', () => {
    const link = mount(document.createElement('a'));
    link.href = '#';
    const span = document.createElement('span');
    span.textContent = 'Docs';
    link.appendChild(span);
    span.click();

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'click: "Docs" (a)', logger: 'interaction'},
    ]);
  });

  it('captures role=button elements', () => {
    const chip = mount(document.createElement('div'));
    chip.setAttribute('role', 'button');
    chip.textContent = 'Express tier';
    chip.click();

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'click: "Express tier" (div)', logger: 'interaction'},
    ]);
  });

  it('ignores clicks on non-interactive elements', () => {
    const paragraph = mount(document.createElement('p'));
    paragraph.textContent = 'just text';
    paragraph.click();

    expect(logsApiMock.postAppLogs).not.toHaveBeenCalled();
  });

  it('truncates long labels', () => {
    const button = mount(document.createElement('button'));
    button.textContent = 'x'.repeat(200);
    button.click();

    const records = logsApiMock.postAppLogs.mock.calls[0][0] as {
      message: string;
    }[];
    expect(records[0].message).toBe(`click: "${'x'.repeat(80)}…" (button)`);
  });

  it('persists form submissions', () => {
    const form = mount(document.createElement('form'));
    form.setAttribute('aria-label', 'Research goal');
    // jsdom aborts real submissions; dispatch the event directly.
    form.dispatchEvent(new Event('submit', {bubbles: true}));

    expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
      {message: 'submit: "Research goal" (form)', logger: 'interaction'},
    ]);
  });

  it('stops capturing after uninstall', () => {
    uninstall();
    const button = mount(document.createElement('button'));
    button.textContent = 'Gone';
    button.click();

    expect(logsApiMock.postAppLogs).not.toHaveBeenCalled();
    uninstall = () => {
      // already uninstalled; afterEach still needs a callable.
    };
  });
});

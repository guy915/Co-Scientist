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
    // Interactions buffer onto a short timer before POSTing; tests drive
    // the flush explicitly.
    vi.useFakeTimers();
    logsApiMock.postAppLogs.mockReset();
    logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
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

  describe('click capture and labeling', () => {
    it('persists clicks on buttons using their visible text', () => {
      const button = mount(document.createElement('button'));
      button.textContent = 'Start run';
      button.click();
      vi.runAllTimers();

      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {message: 'click: "Start run" (button)', logger: 'interaction'},
      ]);
    });

    it('falls back to the aria-label for icon-only controls', () => {
      const button = mount(document.createElement('button'));
      button.setAttribute('aria-label', 'Menu');
      button.click();
      vi.runAllTimers();

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
      vi.runAllTimers();

      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {message: 'click: "Docs" (a)', logger: 'interaction'},
      ]);
    });

    it('captures role=button elements', () => {
      const chip = mount(document.createElement('div'));
      chip.setAttribute('role', 'button');
      chip.textContent = 'Express tier';
      chip.click();
      vi.runAllTimers();

      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {message: 'click: "Express tier" (div)', logger: 'interaction'},
      ]);
    });
  });

  describe('batching and flushing', () => {
    it('batches rapid interactions into one POST', () => {
      const button = mount(document.createElement('button'));
      button.textContent = 'Start run';
      button.click();
      button.click();
      // Nothing ships until the flush timer fires.
      expect(logsApiMock.postAppLogs).not.toHaveBeenCalled();
      vi.runAllTimers();

      expect(logsApiMock.postAppLogs).toHaveBeenCalledTimes(1);
      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {message: 'click: "Start run" (button)', logger: 'interaction'},
        {message: 'click: "Start run" (button)', logger: 'interaction'},
      ]);
    });

    it('flushes immediately once the buffer fills', () => {
      const button = mount(document.createElement('button'));
      button.textContent = 'Go';
      for (let i = 0; i < 20; i++) button.click();

      // The 20th record fills the buffer and ships without the timer.
      expect(logsApiMock.postAppLogs).toHaveBeenCalledTimes(1);
      const records = logsApiMock.postAppLogs.mock.calls[0][0] as unknown[];
      expect(records).toHaveLength(20);
    });

    it('flushes the buffer when the page hides', () => {
      const button = mount(document.createElement('button'));
      button.textContent = 'Start run';
      button.click();
      window.dispatchEvent(new Event('pagehide'));

      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {message: 'click: "Start run" (button)', logger: 'interaction'},
      ]);
      // Already shipped: the timer firing later must not repost it.
      vi.runAllTimers();
      expect(logsApiMock.postAppLogs).toHaveBeenCalledTimes(1);
    });
  });

  describe('capture limits', () => {
    it('ignores clicks on non-interactive elements', () => {
      const paragraph = mount(document.createElement('p'));
      paragraph.textContent = 'just text';
      paragraph.click();
      vi.runAllTimers();

      expect(logsApiMock.postAppLogs).not.toHaveBeenCalled();
    });

    it('truncates long labels', () => {
      const button = mount(document.createElement('button'));
      button.textContent = 'x'.repeat(200);
      button.click();
      vi.runAllTimers();

      const records = logsApiMock.postAppLogs.mock.calls[0][0] as {
        message: string;
      }[];
      expect(records[0].message).toBe(`click: "${'x'.repeat(80)}…" (button)`);
    });
  });

  describe('form submissions and teardown', () => {
    it('persists form submissions', () => {
      const form = mount(document.createElement('form'));
      form.setAttribute('aria-label', 'Research goal');
      // jsdom aborts real submissions; dispatch the event directly.
      form.dispatchEvent(new Event('submit', {bubbles: true}));
      vi.runAllTimers();

      expect(logsApiMock.postAppLogs).toHaveBeenCalledWith([
        {message: 'submit: "Research goal" (form)', logger: 'interaction'},
      ]);
    });

    it('stops capturing after uninstall', () => {
      uninstall();
      const button = mount(document.createElement('button'));
      button.textContent = 'Gone';
      button.click();
      vi.runAllTimers();

      expect(logsApiMock.postAppLogs).not.toHaveBeenCalled();
      uninstall = () => {
        // already uninstalled; afterEach still needs a callable.
      };
    });
  });
});

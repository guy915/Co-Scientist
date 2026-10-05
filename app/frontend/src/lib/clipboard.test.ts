import {afterEach, expect, it, vi} from 'vitest';
import {copyText} from './clipboard';

afterEach(() => {
  Reflect.deleteProperty(navigator, 'clipboard');
  document.body.replaceChildren();
});

it('uses the async Clipboard API when available', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    value: {writeText},
    configurable: true,
  });
  const execCommand = vi.fn();
  Object.defineProperty(document, 'execCommand', {
    value: execCommand,
    configurable: true,
  });

  await copyText('hello world');

  expect(writeText).toHaveBeenCalledWith('hello world');
  expect(execCommand).not.toHaveBeenCalled();
});

it('falls back to execCommand when the clipboard API is absent', async () => {
  Reflect.deleteProperty(navigator, 'clipboard');
  const execCommand = vi.fn().mockReturnValue(true);
  Object.defineProperty(document, 'execCommand', {
    value: execCommand,
    configurable: true,
  });

  await copyText('fallback text');

  expect(execCommand).toHaveBeenCalledWith('copy');
  expect(document.querySelector('textarea')).toBeNull();
});

it('falls back to execCommand when the Clipboard API rejects', async () => {
  const writeText = vi.fn().mockRejectedValue(new Error('denied'));
  Object.defineProperty(navigator, 'clipboard', {
    value: {writeText},
    configurable: true,
  });
  const execCommand = vi.fn().mockReturnValue(true);
  Object.defineProperty(document, 'execCommand', {
    value: execCommand,
    configurable: true,
  });

  await copyText('retry text');

  expect(writeText).toHaveBeenCalledWith('retry text');
  expect(execCommand).toHaveBeenCalledWith('copy');
});

it('never throws when clipboard API and execCommand are absent', async () => {
  Reflect.deleteProperty(navigator, 'clipboard');
  Object.defineProperty(document, 'execCommand', {
    value: () => {
      throw new Error('not supported');
    },
    configurable: true,
  });

  await expect(copyText('no-op')).resolves.toBeUndefined();
});

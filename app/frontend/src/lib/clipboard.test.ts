import {afterEach, describe, expect, it, vi} from 'vitest';
import {copyText} from './clipboard';

afterEach(() => {
  Reflect.deleteProperty(navigator, 'clipboard');
  document.body.replaceChildren();
});

describe('copyText', () => {
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
    // The synchronous fallback must not run when the async API succeeds.
    expect(execCommand).not.toHaveBeenCalled();
  });

  it('falls back to execCommand when navigator.clipboard is unavailable', async () => {
    Reflect.deleteProperty(navigator, 'clipboard');
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      value: execCommand,
      configurable: true,
    });

    await copyText('fallback text');

    expect(execCommand).toHaveBeenCalledWith('copy');
    // The hidden textarea used for the fallback must be cleaned up.
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

  it('builds a readonly, offscreen textarea holding the given text during the fallback', async () => {
    Reflect.deleteProperty(navigator, 'clipboard');
    let capturedValue = '';
    let capturedReadonly: string | null = null;
    Object.defineProperty(document, 'execCommand', {
      value: vi.fn(() => {
        const textarea = document.querySelector('textarea');
        capturedValue = textarea?.value ?? '';
        capturedReadonly = textarea?.getAttribute('readonly') ?? null;
        return true;
      }),
      configurable: true,
    });

    await copyText('snapshot text');

    expect(capturedValue).toBe('snapshot text');
    expect(capturedReadonly).toBe('');
  });

  it('never throws when both the Clipboard API and execCommand are unavailable', async () => {
    Reflect.deleteProperty(navigator, 'clipboard');
    Object.defineProperty(document, 'execCommand', {
      value: () => {
        throw new Error('not supported');
      },
      configurable: true,
    });

    await expect(copyText('no-op')).resolves.toBeUndefined();
  });
});

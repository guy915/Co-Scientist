import {afterEach, describe, expect, it, vi} from 'vitest';
import {makePrefixedId} from './id';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('makePrefixedId', () => {
  it('prefixes a randomUUID-based id when it is available', () => {
    const id = makePrefixedId('user');
    expect(id).toMatch(
      /^user-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });

  it('falls back to timestamp + random when randomUUID is absent', () => {
    vi.stubGlobal('crypto', {});
    const id = makePrefixedId('session');
    expect(id).toMatch(/^session-\d+-[0-9a-f]+$/);
  });

  it('falls back when crypto itself is unavailable', () => {
    vi.stubGlobal('crypto', undefined);
    const id = makePrefixedId('run');
    expect(id).toMatch(/^run-\d+-[0-9a-f]+$/);
  });

  it('produces distinct ids across calls', () => {
    const first = makePrefixedId('id');
    const second = makePrefixedId('id');
    expect(first).not.toBe(second);
  });
});

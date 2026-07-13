import {describe, it, expect, beforeEach, afterEach, vi} from 'vitest';
import {getClientId} from './client_id';

describe('getClientId', () => {
  beforeEach(() => localStorage.removeItem('co_scientist_client_id'));
  afterEach(() => vi.unstubAllGlobals());

  it('generates and persists an id on first use', () => {
    const id = getClientId();
    expect(id).toBeTruthy();
    expect(localStorage.getItem('co_scientist_client_id')).toBe(id);
  });

  it('returns the same id on subsequent calls', () => {
    const first = getClientId();
    const second = getClientId();
    expect(second).toBe(first);
  });

  it('works when randomUUID is unavailable in a non-secure context', () => {
    vi.stubGlobal('crypto', {});

    const id = getClientId();

    expect(id).toMatch(/^client-\d+-[0-9a-f]+$/);
  });
});

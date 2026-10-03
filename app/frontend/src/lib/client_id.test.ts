import {describe, it, expect, beforeEach, afterEach, vi} from 'vitest';
import {
  getClientId,
  DEFAULT_BYOK_PROVIDER,
  getStoredApiKey,
  getStoredApiProvider,
  setStoredApiKey,
  setStoredApiProvider,
} from './client_id';

describe('client id', () => {
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
});

describe('api key', () => {
  const STORAGE_KEY = 'cosci-api-key';
  const PROVIDER_KEY = 'cosci-api-provider';

  afterEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(PROVIDER_KEY);
  });

  describe('getStoredApiKey', () => {
    it('returns an empty string when unset', () => {
      expect(getStoredApiKey()).toBe('');
    });

    it('returns the stored key', () => {
      localStorage.setItem(STORAGE_KEY, 'sk-abc123');
      expect(getStoredApiKey()).toBe('sk-abc123');
    });
  });

  describe('setStoredApiKey', () => {
    it('persists a trimmed key', () => {
      setStoredApiKey('  sk-xyz  ');
      expect(localStorage.getItem(STORAGE_KEY)).toBe('sk-xyz');
    });

    it('removes the entry for an empty value', () => {
      localStorage.setItem(STORAGE_KEY, 'sk-existing');
      setStoredApiKey('');
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('removes the entry for a whitespace-only value', () => {
      localStorage.setItem(STORAGE_KEY, 'sk-existing');
      setStoredApiKey('   ');
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe('getStoredApiProvider', () => {
    it('defaults when unset', () => {
      expect(getStoredApiProvider()).toBe(DEFAULT_BYOK_PROVIDER);
    });

    it('returns the stored provider', () => {
      localStorage.setItem(PROVIDER_KEY, 'openai');
      expect(getStoredApiProvider()).toBe('openai');
    });

    it('falls back to the default for an unknown stored value', () => {
      localStorage.setItem(PROVIDER_KEY, 'skynet');
      expect(getStoredApiProvider()).toBe(DEFAULT_BYOK_PROVIDER);
    });
  });

  describe('setStoredApiProvider', () => {
    it('persists a known provider', () => {
      setStoredApiProvider('gemini');
      expect(localStorage.getItem(PROVIDER_KEY)).toBe('gemini');
    });

    it('persists the default for an unknown provider', () => {
      // Cast: the guard is for values arriving from outside the type.
      setStoredApiProvider('not-a-provider' as never);
      expect(localStorage.getItem(PROVIDER_KEY)).toBe(DEFAULT_BYOK_PROVIDER);
    });
  });
});

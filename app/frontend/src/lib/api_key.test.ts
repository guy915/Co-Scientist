import {afterEach, describe, expect, it} from 'vitest';
import {
  DEFAULT_BYOK_PROVIDER,
  getStoredApiKey,
  getStoredApiProvider,
  setStoredApiKey,
  setStoredApiProvider,
} from './api_key';

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

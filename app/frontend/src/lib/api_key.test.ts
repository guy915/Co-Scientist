import {afterEach, describe, expect, it} from 'vitest';
import {getStoredApiKey, setStoredApiKey} from './api_key';

const STORAGE_KEY = 'cosci-api-key';

afterEach(() => {
  localStorage.removeItem(STORAGE_KEY);
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

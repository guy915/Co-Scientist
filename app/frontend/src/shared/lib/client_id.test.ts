import {describe, it, expect, beforeEach, afterEach, vi} from 'vitest';
import {
  getClientId,
  getStoredApiKey,
  keyedProviders,
  makePrefixedId,
  setStoredApiKey,
} from './client_id';

describe('client id', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.removeItem('co_scientist_client_id');
  });

  it('uses a secure UUID when available', () => {
    const randomUUID = vi.fn(() => '00000000-0000-4000-8000-000000000001');
    vi.stubGlobal('crypto', {randomUUID});
    expect(makePrefixedId('client')).toBe(
      'client-00000000-0000-4000-8000-000000000001',
    );
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  describe('getClientId', () => {
    beforeEach(() => localStorage.removeItem('co_scientist_client_id'));

    it('generates and persists an id on first use', () => {
      const id = getClientId();
      expect(id).toBeTruthy();
      expect(localStorage.getItem('co_scientist_client_id')).toBe(id);
    });

    it('persists and reuses 128 secure random bits when UUIDs are unavailable', () => {
      const getRandomValues = vi.fn((bytes: Uint8Array) => {
        expect(bytes).toHaveLength(16);
        bytes.set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 255]);
        return bytes;
      });
      vi.stubGlobal('crypto', {getRandomValues});
      const insecureRandom = vi.spyOn(Math, 'random');

      const id = getClientId();
      expect(id).toBe('client-000102030405060708090a0b0c0d0eff');
      expect(localStorage.getItem('co_scientist_client_id')).toBe(id);
      expect(getClientId()).toBe(id);
      expect(getRandomValues).toHaveBeenCalledOnce();
      expect(insecureRandom).not.toHaveBeenCalled();
    });

    it('does not persist an ownership ID without secure randomness', () => {
      vi.stubGlobal('crypto', undefined);
      expect(() => getClientId()).toThrow('Secure randomness is required');
      expect(localStorage.getItem('co_scientist_client_id')).toBeNull();
    });
  });
});

describe('api keys', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('keeps one trimmed key per provider', () => {
    setStoredApiKey('  sk-a  ', 'anthropic');
    setStoredApiKey('sk-g', 'gemini');
    expect(getStoredApiKey('anthropic')).toBe('sk-a');
    expect(getStoredApiKey('gemini')).toBe('sk-g');
    expect(getStoredApiKey('openai')).toBe('');
    expect(keyedProviders()).toEqual(['anthropic', 'gemini']);
  });
});

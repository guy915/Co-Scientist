import {describe, it, expect, beforeEach, afterEach, vi} from 'vitest';
import {
  getClientId,
  getStoredApiKey,
  getStoredModel,
  keyedProviders,
  setStoredApiKey,
  setStoredModel,
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

    it('works when randomUUID is unavailable in a non-secure context', () => {
      vi.stubGlobal('crypto', {});

      const id = getClientId();

      expect(id).toMatch(/^client-\d+-[0-9a-f]+$/);
    });
  });
});

describe('api keys', () => {
  const PROVIDER_KEY = 'cosci-api-provider';

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

  it('clearing a key leaves other keys and drops its model choices', () => {
    setStoredApiKey('sk-a', 'anthropic');
    setStoredApiKey('sk-g', 'gemini');
    setStoredModel('worker', {provider: 'gemini', model: 'gemini/x'});
    setStoredModel('supervisor', {provider: 'anthropic', model: 'anthropic/y'});
    setStoredApiKey('   ', 'gemini');
    expect(keyedProviders()).toEqual(['anthropic']);
    expect(getStoredModel('worker')).toBeNull();
    expect(getStoredModel('supervisor')?.model).toBe('anthropic/y');
  });

  it('migrates the single legacy key to its stored provider once', () => {
    localStorage.setItem('cosci-api-key', 'sk-old');
    localStorage.setItem(PROVIDER_KEY, 'openai');
    expect(getStoredApiKey('openai')).toBe('sk-old');
    expect(getStoredApiKey('anthropic')).toBe('');
    expect(localStorage.getItem('cosci-api-key')).toBeNull();
    setStoredApiKey('', 'openai');
    expect(keyedProviders()).toEqual([]);
  });

  it('treats corrupt stored keys and models as empty', () => {
    localStorage.setItem('cosci-api-keys', '{not json');
    localStorage.setItem('cosci-api-model', '{not json');
    expect(keyedProviders()).toEqual([]);
    expect(getStoredModel('worker')).toBeNull();
  });
});

import {describe, it, expect, beforeEach, afterEach} from 'vitest';
import {
  getClientId,
  getStoredApiKey,
  keyedProviders,
  setStoredApiKey,
} from './client_id';

describe('client id', () => {
  describe('getClientId', () => {
    beforeEach(() => localStorage.removeItem('co_scientist_client_id'));

    it('generates and persists an id on first use', () => {
      const id = getClientId();
      expect(id).toBeTruthy();
      expect(localStorage.getItem('co_scientist_client_id')).toBe(id);
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

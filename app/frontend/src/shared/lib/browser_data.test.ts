import {afterEach, expect, it, vi} from 'vitest';
import {browserSettings, clearBrowserData} from './browser_data';
import {STORAGE_KEYS} from './safe_storage';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

it('exports preferences without reading saved credentials or the owner token', () => {
  localStorage.setItem(STORAGE_KEYS.theme, 'dark');
  localStorage.setItem(STORAGE_KEYS.apiKeys, 'PRIVATE_KEY');
  localStorage.setItem(STORAGE_KEYS.legacyApiKey, 'PRIVATE_LEGACY_KEY');
  localStorage.setItem(STORAGE_KEYS.clientId, 'PRIVATE_OWNER');
  localStorage.setItem(
    STORAGE_KEYS.customModels,
    JSON.stringify({openai: 'custom-model'}),
  );
  localStorage.setItem(STORAGE_KEYS.sessionSidePrefix + 'run-one', 'report');
  localStorage.setItem(STORAGE_KEYS.sessionTabPrefix + 'run-one', 'overview');
  const reads = vi.spyOn(Storage.prototype, 'getItem');
  const result = browserSettings();
  expect(result.theme).toBe('dark');
  expect(result.custom_models).toEqual({openai: 'custom-model'});
  expect(result.session_views[STORAGE_KEYS.sessionSidePrefix + 'run-one']).toBe(
    'report',
  );
  expect(result.session_views[STORAGE_KEYS.sessionTabPrefix + 'run-one']).toBe(
    'overview',
  );
  expect(JSON.stringify(result)).not.toContain('PRIVATE_');
  expect(reads.mock.calls.flat()).not.toContain(STORAGE_KEYS.apiKeys);
  expect(reads.mock.calls.flat()).not.toContain(STORAGE_KEYS.legacyApiKey);
  expect(reads.mock.calls.flat()).not.toContain(STORAGE_KEYS.clientId);
});

it('removes credentials, pending retries and per-run choices while preserving unrelated storage', () => {
  for (const store of [localStorage, sessionStorage]) {
    for (const key of Object.values(STORAGE_KEYS))
      store.setItem(key, 'private');
    store.setItem(STORAGE_KEYS.sessionSidePrefix + 'run-one', 'report');
    store.setItem(STORAGE_KEYS.pendingRunCreatePrefix + 'chat-one', 'retry');
    store.setItem(STORAGE_KEYS.sessionTabPrefix + 'run-one', 'overview');
    store.setItem('another-app', 'preserved');
  }
  expect(clearBrowserData()).toBe(true);
  for (const store of [localStorage, sessionStorage]) {
    expect(store.length).toBe(1);
    expect(store.getItem('another-app')).toBe('preserved');
  }
});

it('reports blocked browser cleanup and still clears the accessible store', () => {
  sessionStorage.setItem(STORAGE_KEYS.logsBaseline, 'private');
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
    throw new DOMException('blocked', 'SecurityError');
  });
  expect(clearBrowserData()).toBe(false);
  expect(sessionStorage.length).toBe(0);
  expect(browserSettings().theme).toBeNull();
});

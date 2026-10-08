import {afterEach, expect, it, vi} from 'vitest';
import {subscribeDataErasure} from './data_erasure_sync';
import {STORAGE_KEYS} from './safe_storage';

function changed(oldValue: string) {
  const event = new StorageEvent('storage', {
    key: STORAGE_KEYS.clientId,
    oldValue,
    newValue: null,
  });
  Object.defineProperty(event, 'storageArea', {value: window.localStorage});
  return event;
}

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

it('clears another open tab before it can reuse erased keys or pending requests', () => {
  localStorage.setItem(STORAGE_KEYS.clientId, 'owner-one');
  localStorage.setItem(STORAGE_KEYS.apiKeys, 'private-key');
  sessionStorage.setItem(
    STORAGE_KEYS.pendingRunCreatePrefix + 'chat',
    'private-request',
  );
  const reload = vi.fn();
  const stop = subscribeDataErasure(reload);
  try {
    const event = changed('owner-one');
    window.dispatchEvent(event);
    window.dispatchEvent(event);
    expect(reload).toHaveBeenCalledOnce();
    expect(localStorage.getItem(STORAGE_KEYS.apiKeys)).toBeNull();
    expect(sessionStorage.length).toBe(0);
  } finally {
    stop();
  }
});

it('ignores another identity and unrelated storage changes, and unsubscribes', () => {
  localStorage.setItem(STORAGE_KEYS.clientId, 'owner-one');
  const reload = vi.fn();
  const stop = subscribeDataErasure(reload);
  window.dispatchEvent(changed('owner-other'));
  expect(reload).not.toHaveBeenCalled();
  stop();
  window.dispatchEvent(changed('owner-one'));
  expect(reload).not.toHaveBeenCalled();
});

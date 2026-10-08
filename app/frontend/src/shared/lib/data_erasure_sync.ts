import {getClientId} from './client_id';
import {clearBrowserData} from './browser_data';
import {readStorage, STORAGE_KEYS} from './safe_storage';

export function subscribeDataErasure(onErased: () => void): () => void {
  const owner = getClientId();
  let erased = false;
  function changed(event: StorageEvent) {
    if (erased || event.storageArea !== window.localStorage) return;
    const removed =
      event.key === STORAGE_KEYS.clientId &&
      event.oldValue === owner &&
      event.newValue === null;
    const cleared =
      event.key === null &&
      readStorage('local', STORAGE_KEYS.clientId) === null;
    if (!removed && !cleared) return;
    erased = true;
    clearBrowserData();
    onErased();
  }
  window.addEventListener('storage', changed);
  return () => window.removeEventListener('storage', changed);
}

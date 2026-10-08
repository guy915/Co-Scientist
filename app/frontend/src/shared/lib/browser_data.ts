import {readStorage, STORAGE_KEYS} from './safe_storage';

export function browserSettings() {
  let customModels: Record<string, string> = {};
  try {
    const raw = JSON.parse(
      readStorage('local', STORAGE_KEYS.customModels) ?? '{}',
    );
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
      customModels = Object.fromEntries(
        Object.entries(raw).map(([key, value]) => [
          key,
          typeof value === 'string' ? value : JSON.stringify(value),
        ]),
      );
    }
  } catch {
    customModels = {};
  }
  const sessionViews: Record<string, string> = {};
  try {
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index);
      if (
        key &&
        (key === STORAGE_KEYS.lastSessionSide ||
          key.startsWith(STORAGE_KEYS.sessionSidePrefix) ||
          key.startsWith(STORAGE_KEYS.sessionTabPrefix))
      )
        sessionViews[key] = localStorage.getItem(key) ?? '';
    }
  } catch {
    // An inaccessible browser store contains no preferences we can export.
  }
  const theme = readStorage('local', STORAGE_KEYS.theme);
  return {
    theme: ['light', 'dark', 'system'].includes(theme ?? '') ? theme : null,
    provider: readStorage('local', STORAGE_KEYS.apiProvider),
    worker_model: readStorage('local', STORAGE_KEYS.workerModel),
    supervisor_model: readStorage('local', STORAGE_KEYS.supervisorModel),
    custom_models: customModels,
    session_views: sessionViews,
  };
}

export function clearBrowserData(): boolean {
  const exact = new Set<string>(Object.values(STORAGE_KEYS));
  const prefixes = [...exact].filter(key => key.endsWith(':'));
  let cleared = true;
  for (const kind of ['localStorage', 'sessionStorage'] as const) {
    try {
      const store = window[kind];
      const keys = Array.from({length: store.length}, (_, index) =>
        store.key(index),
      );
      for (const key of keys) {
        if (
          key &&
          (exact.has(key) || prefixes.some(prefix => key.startsWith(prefix)))
        )
          store.removeItem(key);
      }
    } catch {
      cleared = false;
    }
  }
  return cleared;
}

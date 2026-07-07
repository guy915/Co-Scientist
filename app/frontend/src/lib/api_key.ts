// Client-side storage for the user's LLM API key (Settings > Model). The key
// never leaves the browser; runs use it only once the backend grows a
// bring-your-own-key path.

const STORAGE_KEY = 'cosci-api-key';

/**
 * Reads the stored API key.
 *
 * @returns The stored key, or an empty string when unset.
 */
export function getStoredApiKey(): string {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(STORAGE_KEY) ?? '';
}

/**
 * Persists the API key, or removes it when blank.
 *
 * @param value The key to store; whitespace-only values clear the entry.
 */
export function setStoredApiKey(value: string): void {
  const trimmed = value.trim();
  if (trimmed) {
    window.localStorage.setItem(STORAGE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}

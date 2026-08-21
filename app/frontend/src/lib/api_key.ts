// Client-side storage for the user's bring-your-own-key (BYOK) LLM
// credentials (Settings > Model). The key and the chosen provider live in
// localStorage; they are sent to the backend as request headers
// (X-LLM-API-Key / X-LLM-Provider, see api/runs_http.ts byokHeaders) on run
// creation and on the interview/Q&A paths, where the key is validated and
// stored encrypted for the run's lifetime.

const STORAGE_KEY = 'cosci-api-key';
const PROVIDER_KEY = 'cosci-api-provider';

/**
 * Providers offered for BYOK runs. Must stay within the backend's
 * PROVIDER_CREDENTIAL_ENV set (app/app/config.py); the backend rejects
 * anything else. A subset is fine -- azure is deliberately not offered
 * here (a single API key is not enough to reach an Azure deployment), and
 * a stored `azure` choice from before falls back to the default below.
 */
export const BYOK_PROVIDERS = [
  'anthropic',
  'deepseek',
  'gemini',
  'openai',
  'openrouter',
] as const;

/** One provider a user may bring their own key for. */
export type ByokProvider = (typeof BYOK_PROVIDERS)[number];

/** The provider selected when the user has not chosen one. */
export const DEFAULT_BYOK_PROVIDER: ByokProvider = 'deepseek';

/**
 * Reads the stored API key.
 *
 * @returns The stored key, or an empty string when unset.
 */
export function getStoredApiKey(): string {
  // guards SSR/non-browser environments
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

/**
 * Reads the stored BYOK provider choice.
 *
 * @returns The stored provider when it is a known one, else the default.
 */
export function getStoredApiProvider(): ByokProvider {
  if (typeof window === 'undefined') return DEFAULT_BYOK_PROVIDER;
  const stored = window.localStorage.getItem(PROVIDER_KEY) ?? '';
  return (BYOK_PROVIDERS as readonly string[]).includes(stored)
    ? (stored as ByokProvider)
    : DEFAULT_BYOK_PROVIDER;
}

/**
 * Persists the BYOK provider choice.
 *
 * @param provider The provider to store; unknown values store the default.
 */
export function setStoredApiProvider(provider: ByokProvider): void {
  const known = (BYOK_PROVIDERS as readonly string[]).includes(provider)
    ? provider
    : DEFAULT_BYOK_PROVIDER;
  window.localStorage.setItem(PROVIDER_KEY, known);
}

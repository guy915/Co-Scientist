// localStorage key; sent as X-Client-ID to scope owned runs
const KEY = 'co_scientist_client_id';
const ACCESS_TOKEN_KEY = 'co_scientist_access_token';

/**
 * Returns the persistent client id, generating and storing one on first use.
 *
 * @returns The client id from localStorage, or a freshly created UUID.
 */
export function getClientId(): string {
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = makePrefixedId('client');
    localStorage.setItem(KEY, id);
  }
  return id;
}

/** Return the server-signed researcher session, when authenticated. */
export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_TOKEN_KEY);
}

/** Persist a server-signed researcher session for this browser tab. */
export function setAccessToken(token: string): void {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, token);
}

/** Remove the current researcher session. */
export function clearAccessToken(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
}

/**
 * Generates an opaque, ephemeral id with a human-readable prefix.
 *
 * Prefers the platform's `crypto.randomUUID` for collision resistance and falls
 * back to a timestamp plus random suffix where it is unavailable.
 *
 * @param prefix Short label prepended to the generated id (e.g. "user").
 * @returns A prefixed id such as `user-<uuid>`.
 */
export function makePrefixedId(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// Client-side storage for the user's bring-your-own-key (BYOK) LLM
// credentials (Settings > Model). The key and the chosen provider live in
// localStorage; they are sent to the backend as request headers
// (X-LLM-API-Key / X-LLM-Provider, see api/runs_http.ts byokHeaders) on run
// creation and on the interview/Q&A paths, where the key is validated and
// stored encrypted for the run's lifetime.

const STORAGE_KEY = 'cosci-api-key';
const PROVIDER_KEY = 'cosci-api-provider';

/**
 * The two model tiers a BYOK user picks in Settings > Model: `worker` runs
 * generation, review, ranking, and chat; `supervisor` runs planning,
 * meta-review, and the final overview.
 */
export type ModelTier = 'worker' | 'supervisor';

const MODEL_KEYS: Record<ModelTier, string> = {
  worker: 'cosci-api-model',
  supervisor: 'cosci-api-supervisor-model',
};

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
  // Models are provider-specific, so a new provider starts on its defaults.
  if (known !== getStoredApiProvider()) {
    setStoredModel('worker', '');
    setStoredModel('supervisor', '');
  }
  window.localStorage.setItem(PROVIDER_KEY, known);
}

/**
 * Reads the stored model choice for one tier.
 *
 * @param tier The model tier.
 * @returns The stored litellm model id, or an empty string for the
 *   provider's default.
 */
export function getStoredModel(tier: ModelTier): string {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(MODEL_KEYS[tier]) ?? '';
}

/**
 * Persists one tier's model choice, or removes it when blank.
 *
 * @param tier The model tier.
 * @param model The litellm model id; blank means the provider's default.
 */
export function setStoredModel(tier: ModelTier, model: string): void {
  if (model) {
    window.localStorage.setItem(MODEL_KEYS[tier], model);
  } else {
    window.localStorage.removeItem(MODEL_KEYS[tier]);
  }
}

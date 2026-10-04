const KEY = 'co_scientist_client_id';
const ACCESS_TOKEN_KEY = 'co_scientist_access_token';

export function getClientId(): string {
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = makePrefixedId('client');
    localStorage.setItem(KEY, id);
  }
  return id;
}

// Researcher sessions are tab-scoped; anonymous client identity persists across
// tabs.
export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
}

export function makePrefixedId(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// BYOK browser credentials travel only as headers; the backend validates and
// stores them encrypted for the run lifetime.

const STORAGE_KEY = 'cosci-api-key';
const PROVIDER_KEY = 'cosci-api-provider';

export type ModelTier = 'worker' | 'supervisor';

const MODEL_KEYS: Record<ModelTier, string> = {
  worker: 'cosci-api-model',
  supervisor: 'cosci-api-supervisor-model',
};

// Providers must be accepted by the backend credential map. Azure needs
// deployment configuration beyond one API key and is deliberately omitted.
export const BYOK_PROVIDERS = [
  'anthropic',
  'deepseek',
  'gemini',
  'openai',
  'openrouter',
] as const;

export type ByokProvider = (typeof BYOK_PROVIDERS)[number];

export const DEFAULT_BYOK_PROVIDER: ByokProvider = 'deepseek';

export function getStoredApiKey(): string {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(STORAGE_KEY) ?? '';
}

export function setStoredApiKey(value: string): void {
  const trimmed = value.trim();
  if (trimmed) {
    window.localStorage.setItem(STORAGE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}

export function getStoredApiProvider(): ByokProvider {
  if (typeof window === 'undefined') return DEFAULT_BYOK_PROVIDER;
  const stored = window.localStorage.getItem(PROVIDER_KEY) ?? '';
  return (BYOK_PROVIDERS as readonly string[]).includes(stored)
    ? (stored as ByokProvider)
    : DEFAULT_BYOK_PROVIDER;
}

export function setStoredApiProvider(provider: ByokProvider): void {
  const known = (BYOK_PROVIDERS as readonly string[]).includes(provider)
    ? provider
    : DEFAULT_BYOK_PROVIDER;
  // Model choices are provider-specific; changing provider must discard its
  // previous selections.
  if (known !== getStoredApiProvider()) {
    setStoredModel('worker', '');
    setStoredModel('supervisor', '');
  }
  window.localStorage.setItem(PROVIDER_KEY, known);
}

export function getStoredModel(tier: ModelTier): string {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(MODEL_KEYS[tier]) ?? '';
}

export function setStoredModel(tier: ModelTier, model: string): void {
  if (model) {
    window.localStorage.setItem(MODEL_KEYS[tier], model);
  } else {
    window.localStorage.removeItem(MODEL_KEYS[tier]);
  }
}

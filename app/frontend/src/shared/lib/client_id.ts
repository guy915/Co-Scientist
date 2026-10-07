import {
  readStorage,
  removeStorage,
  STORAGE_KEYS,
  writeStorage,
} from './safe_storage';

// Without storage the id lives for this page load, so requests still carry
// one stable owner instead of throwing out of every scoped call.
let memoryClientId: string | null = null;

export function getClientId(): string {
  const stored = readStorage('local', STORAGE_KEYS.clientId);
  if (stored) return stored;
  if (memoryClientId) return memoryClientId;
  const id = makePrefixedId('client');
  if (!writeStorage('local', STORAGE_KEYS.clientId, id)) memoryClientId = id;
  return id;
}

export function makePrefixedId(prefix: string): string {
  if (typeof crypto === 'undefined') {
    throw new Error('Secure randomness is required to create an ownership ID');
  }
  if (typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const id = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join(
    '',
  );
  return `${prefix}-${id}`;
}

// BYOK browser credentials travel only as headers; the backend validates and
// stores them encrypted for the run lifetime.

const KEYS_STORAGE = STORAGE_KEYS.apiKeys;
const LEGACY_KEY_STORAGE = STORAGE_KEYS.legacyApiKey;
const PROVIDER_KEY = STORAGE_KEYS.apiProvider;

export type ModelTier = 'worker' | 'supervisor';

const MODEL_KEYS: Record<ModelTier, string> = {
  worker: STORAGE_KEYS.workerModel,
  supervisor: STORAGE_KEYS.supervisorModel,
};
const TIERS = Object.keys(MODEL_KEYS) as ModelTier[];

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

// A model's provider is recorded when it is chosen from the catalog, so request
// headers never infer it from the model string.
export interface ModelChoice {
  provider: ByokProvider;
  model: string;
}

type ApiKeys = Partial<Record<ByokProvider, string>>;

function isProvider(value: unknown): value is ByokProvider {
  return (BYOK_PROVIDERS as readonly unknown[]).includes(value);
}

export function getStoredApiProvider(): ByokProvider {
  const stored = readStorage('local', PROVIDER_KEY);
  return isProvider(stored) ? stored : DEFAULT_BYOK_PROVIDER;
}

// The single-key layout stored one key and plain model names for the stored
// provider. Convert before anything reads or changes that provider.
function migrateLegacy(): void {
  const provider = getStoredApiProvider();
  const legacyKey = readStorage('local', LEGACY_KEY_STORAGE);
  if (legacyKey !== null) {
    removeStorage('local', LEGACY_KEY_STORAGE);
    if (!readStorage('local', KEYS_STORAGE) && legacyKey.trim()) {
      const keys = {[provider]: legacyKey.trim()};
      // codeql[js/clear-text-storage-of-sensitive-data] Intentional BYOK browser vault; keys travel as headers.
      window.localStorage.setItem(KEYS_STORAGE, JSON.stringify(keys));
    }
  }
  for (const tier of TIERS) {
    const raw = readStorage('local', MODEL_KEYS[tier]);
    if (raw && !raw.startsWith('{')) {
      writeStorage(
        'local',
        MODEL_KEYS[tier],
        JSON.stringify({provider, model: raw}),
      );
    }
  }
}

function readKeys(): ApiKeys {
  migrateLegacy();
  try {
    const parsed = JSON.parse(
      readStorage('local', KEYS_STORAGE) ?? '{}',
    ) as Record<string, unknown>;
    const keys: ApiKeys = {};
    for (const provider of BYOK_PROVIDERS) {
      const key = parsed[provider];
      if (typeof key === 'string' && key) keys[provider] = key;
    }
    return keys;
  } catch {
    return {};
  }
}

export function getStoredApiKey(
  provider: ByokProvider = getStoredApiProvider(),
): string {
  return readKeys()[provider] ?? '';
}

// Providers with a saved key, in catalog order.
export function keyedProviders(): ByokProvider[] {
  const keys = readKeys();
  return BYOK_PROVIDERS.filter(provider => provider in keys);
}

export function setStoredApiKey(
  value: string,
  provider: ByokProvider = getStoredApiProvider(),
): void {
  const keys = readKeys();
  const trimmed = value.trim();
  // JSON omits the undefined entry of a cleared key.
  keys[provider] = trimmed || undefined;
  if (!trimmed) {
    // A model that can no longer be paid for must not outlive its key.
    for (const tier of TIERS) {
      if (getStoredModel(tier)?.provider === provider) {
        setStoredModel(tier, null);
      }
    }
  }
  // codeql[js/clear-text-storage-of-sensitive-data] Intentional BYOK browser vault; keys travel as headers.
  window.localStorage.setItem(KEYS_STORAGE, JSON.stringify(keys));
}

export function setStoredApiProvider(provider: ByokProvider): void {
  migrateLegacy();
  writeStorage(
    'local',
    PROVIDER_KEY,
    isProvider(provider) ? provider : DEFAULT_BYOK_PROVIDER,
  );
}

export function getStoredModel(tier: ModelTier): ModelChoice | null {
  migrateLegacy();
  try {
    const parsed = JSON.parse(
      readStorage('local', MODEL_KEYS[tier]) ?? 'null',
    ) as Partial<ModelChoice> | null;
    return parsed && isProvider(parsed.provider) && parsed.model
      ? {provider: parsed.provider, model: parsed.model}
      : null;
  } catch {
    return null;
  }
}

export function setStoredModel(
  tier: ModelTier,
  choice: ModelChoice | null,
): void {
  if (choice) {
    writeStorage('local', MODEL_KEYS[tier], JSON.stringify(choice));
  } else {
    removeStorage('local', MODEL_KEYS[tier]);
  }
}

// The provider a tier uses without a usable choice: the one being viewed, or
// the first with a key. The backend then supplies that provider's default.
export function fallbackProvider(
  keyed: readonly ByokProvider[] = keyedProviders(),
  viewed: ByokProvider = getStoredApiProvider(),
): ByokProvider {
  return keyed.includes(viewed) ? viewed : (keyed[0] ?? viewed);
}

export interface ByokRoute {
  provider: ByokProvider;
  apiKey: string;
  model: string | null;
}

// A stored choice only counts while its provider still has a key; otherwise
// the tier falls back to a keyed provider's default. A tier without a choice
// follows the worker's provider. Null means no key is saved at all.
export function resolveByokRoutes(): {
  worker: ByokRoute;
  supervisor: ByokRoute;
} | null {
  const keyed = keyedProviders();
  if (keyed.length === 0) return null;
  const route = (tier: ModelTier, fallback: ByokProvider): ByokRoute => {
    const choice = getStoredModel(tier);
    const usable = choice && keyed.includes(choice.provider) ? choice : null;
    const provider = usable?.provider ?? fallback;
    return {
      provider,
      apiKey: getStoredApiKey(provider),
      model: usable?.model ?? null,
    };
  };
  const worker = route('worker', fallbackProvider(keyed));
  return {worker, supervisor: route('supervisor', worker.provider)};
}

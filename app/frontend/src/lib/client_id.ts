const KEY = 'co_scientist_client_id';

export function getClientId(): string {
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = makePrefixedId('client');
    localStorage.setItem(KEY, id);
  }
  return id;
}

export function makePrefixedId(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// BYOK browser credentials travel only as headers; the backend validates and
// stores them encrypted for the run lifetime.

const KEYS_STORAGE = 'cosci-api-keys';
const LEGACY_KEY_STORAGE = 'cosci-api-key';
const PROVIDER_KEY = 'cosci-api-provider';

export type ModelTier = 'worker' | 'supervisor';

const MODEL_KEYS: Record<ModelTier, string> = {
  worker: 'cosci-api-model',
  supervisor: 'cosci-api-supervisor-model',
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
  const stored = window.localStorage.getItem(PROVIDER_KEY);
  return isProvider(stored) ? stored : DEFAULT_BYOK_PROVIDER;
}

// The single-key layout stored one key and plain model names for the stored
// provider. Convert before anything reads or changes that provider.
function migrateLegacy(): void {
  const store = window.localStorage;
  const provider = getStoredApiProvider();
  const legacyKey = store.getItem(LEGACY_KEY_STORAGE);
  if (legacyKey !== null) {
    store.removeItem(LEGACY_KEY_STORAGE);
    if (!store.getItem(KEYS_STORAGE) && legacyKey.trim()) {
      const keys = {[provider]: legacyKey.trim()};
      store.setItem(KEYS_STORAGE, JSON.stringify(keys));
    }
  }
  for (const tier of TIERS) {
    const raw = store.getItem(MODEL_KEYS[tier]);
    if (raw && !raw.startsWith('{')) {
      store.setItem(MODEL_KEYS[tier], JSON.stringify({provider, model: raw}));
    }
  }
}

function readKeys(): ApiKeys {
  migrateLegacy();
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(KEYS_STORAGE) ?? '{}',
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
  window.localStorage.setItem(KEYS_STORAGE, JSON.stringify(keys));
}

export function setStoredApiProvider(provider: ByokProvider): void {
  migrateLegacy();
  window.localStorage.setItem(
    PROVIDER_KEY,
    isProvider(provider) ? provider : DEFAULT_BYOK_PROVIDER,
  );
}

export function getStoredModel(tier: ModelTier): ModelChoice | null {
  migrateLegacy();
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(MODEL_KEYS[tier]) ?? 'null',
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
    window.localStorage.setItem(MODEL_KEYS[tier], JSON.stringify(choice));
  } else {
    window.localStorage.removeItem(MODEL_KEYS[tier]);
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

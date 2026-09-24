import {getStoredApiKey, getStoredApiProvider} from '@/lib/api_key';
import {getAccessToken, getClientId} from '@/lib/client_id';
import {makePrefixedId} from '@/lib/id';

const STORAGE_PREFIX = 'co_scientist_pending_run_create:';

interface StoredIntent {
  version: 1;
  key: string;
  ownerFingerprint: string;
  byokFingerprint: string;
  payloadJson: string;
}

/** Returns one exact, owner- and credential-scoped create request per chat. */
export async function getPendingCreateIntent<T extends Record<string, unknown>>(
  chatId: string,
  payload: T,
): Promise<{key: string; payload: T}> {
  const storageKey = `${STORAGE_PREFIX}${encodeURIComponent(chatId)}`;
  const payloadJson = JSON.stringify(payload);
  const [ownerFingerprint, byokFingerprint] = await Promise.all([
    fingerprint(ownerMaterial()),
    fingerprint(credentialMaterial()),
  ]);

  const stored = readIntent(storageKey);
  if (matchesIntent(stored, ownerFingerprint, byokFingerprint, payloadJson)) {
    return {key: stored.key, payload: JSON.parse(stored.payloadJson) as T};
  }

  const intent: StoredIntent = {
    version: 1,
    key: makePrefixedId('run-create'),
    ownerFingerprint,
    byokFingerprint,
    payloadJson,
  };
  sessionStorage.setItem(storageKey, JSON.stringify(intent));
  return {key: intent.key, payload: JSON.parse(payloadJson) as T};
}

function ownerMaterial(): string {
  const token = getAccessToken();
  return token ? `researcher:${token}` : `client:${getClientId()}`;
}

function credentialMaterial(): string {
  const apiKey = getStoredApiKey();
  return apiKey ? `${getStoredApiProvider()}\u0000${apiKey}` : '';
}

function matchesIntent(
  intent: StoredIntent | undefined,
  ownerFingerprint: string,
  byokFingerprint: string,
  payloadJson: string,
): intent is StoredIntent {
  return Boolean(
    intent &&
    intent.ownerFingerprint === ownerFingerprint &&
    intent.byokFingerprint === byokFingerprint &&
    intent.payloadJson === payloadJson,
  );
}

function readIntent(key: string): StoredIntent | undefined {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    return isStoredIntent(parsed) ? parsed : undefined;
  } catch {
    // A damaged session entry is replaced by a fresh request intent.
  }
  return undefined;
}

function isStoredIntent(value: unknown): value is StoredIntent {
  if (!isRecord(value) || value.version !== 1) return false;
  const stringFields = [
    'key',
    'ownerFingerprint',
    'byokFingerprint',
    'payloadJson',
  ] as const;
  return stringFields.every(field => typeof value[field] === 'string');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

async function fingerprint(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), byte =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
}

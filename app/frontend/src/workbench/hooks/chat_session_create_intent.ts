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
  createdRunId?: string;
}

export interface PendingCreateIntent<
  T extends Record<string, unknown> = Record<string, unknown>,
> {
  key: string;
  payload: T;
  createdRunId?: string;
}

/** Returns one exact, owner- and credential-scoped create request per chat. */
export async function getPendingCreateIntent<T extends Record<string, unknown>>(
  chatId: string,
  payload: T,
): Promise<{key: string; payload: T; createdRunId?: string}> {
  const storageKey = `${STORAGE_PREFIX}${encodeURIComponent(chatId)}`;
  const payloadJson = JSON.stringify(payload);
  const [ownerFingerprint, byokFingerprint] = await Promise.all([
    fingerprint(ownerMaterial()),
    fingerprint(credentialMaterial()),
  ]);

  const stored = readIntent(storageKey);
  if (matchesIntent(stored, ownerFingerprint, byokFingerprint, payloadJson)) {
    return {
      key: stored.key,
      payload: JSON.parse(stored.payloadJson) as T,
      createdRunId: stored.createdRunId,
    };
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

/** Reads the exact pending request for this chat and owner without rebuilding it. */
export async function readPendingCreateIntent<
  T extends Record<string, unknown> = Record<string, unknown>,
>(chatId: string): Promise<PendingCreateIntent<T> | undefined> {
  const [ownerFingerprint, byokFingerprint] = await Promise.all([
    fingerprint(ownerMaterial()),
    fingerprint(credentialMaterial()),
  ]);
  const intent = readIntent(intentStorageKey(chatId));
  if (!intent || !matchesOwner(intent, ownerFingerprint, byokFingerprint)) {
    return undefined;
  }

  return publicIntent<T>(intent);
}

function matchesOwner(
  intent: StoredIntent,
  ownerFingerprint: string,
  byokFingerprint: string,
): boolean {
  return (
    intent.ownerFingerprint === ownerFingerprint &&
    intent.byokFingerprint === byokFingerprint
  );
}

function publicIntent<T extends Record<string, unknown>>(
  intent: StoredIntent,
): PendingCreateIntent<T> | undefined {
  try {
    const payload: unknown = JSON.parse(intent.payloadJson);
    if (!isRecord(payload) || Array.isArray(payload)) return undefined;
    return {
      key: intent.key,
      payload: payload as T,
      createdRunId: intent.createdRunId,
    };
  } catch {
    return undefined;
  }
}

/** Records the known run without changing the request's idempotency key. */
export function rememberPendingCreateRun(
  chatId: string,
  key: string,
  runId: string,
): void {
  const storageKey = intentStorageKey(chatId);
  const intent = readIntent(storageKey);
  if (!intent || intent.key !== key) return;
  sessionStorage.setItem(
    storageKey,
    JSON.stringify({...intent, createdRunId: runId}),
  );
}

/** Removes only the intent whose request key has reached a settled outcome. */
export function retirePendingCreateIntent(chatId: string, key: string): void {
  const storageKey = intentStorageKey(chatId);
  if (readIntent(storageKey)?.key === key) {
    sessionStorage.removeItem(storageKey);
  }
}

function intentStorageKey(chatId: string): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(chatId)}`;
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
  if (
    value.createdRunId !== undefined &&
    typeof value.createdRunId !== 'string'
  ) {
    return false;
  }
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

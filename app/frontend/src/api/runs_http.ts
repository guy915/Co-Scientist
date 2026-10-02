import {clearAccessToken, getAccessToken, getClientId} from '@/lib/client_id';
import {
  getStoredApiKey,
  getStoredApiProvider,
  getStoredModel,
} from '@/lib/api_key';

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || '';

/** Exchange a configured researcher invite code for a signed session. */
export function exchangeAccessCode(
  accessCode: string,
): Promise<{access_token: string; researcher_id: string; expires_in: number}> {
  return fetchJson(
    '/api/auth/exchange',
    jsonRequest({access_code: accessCode}),
  );
}

/** Researcher sessions take precedence over anonymous browser identities. */
export function clientHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token
    ? {Authorization: `Bearer ${token}`}
    : {'X-Client-ID': getClientId()};
}

/** BYOK credentials and model choices travel only in request headers. */
export function byokHeaders(): Record<string, string> {
  const apiKey = getStoredApiKey();
  if (!apiKey) return {};
  const worker = getStoredModel('worker');
  const supervisor = getStoredModel('supervisor');
  return {
    'X-LLM-API-Key': apiKey,
    'X-LLM-Provider': getStoredApiProvider(),
    // Omitted when unset: the backend then runs the provider's default.
    ...(worker ? {'X-LLM-Model': worker} : {}),
    ...(supervisor ? {'X-LLM-Supervisor-Model': supervisor} : {}),
  };
}

/** Keeps status available to callers that distinguish conflicts/failures. */
export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

async function responseErrorMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => res.statusText);
  if (res.status === 500 && !text.trim()) return 'API unavailable';
  // Usage-limit refusals carry reader-facing instructions in `detail`.
  if (res.status === 403 || res.status === 429) {
    try {
      const detail: unknown = (JSON.parse(text) as {detail?: unknown}).detail;
      if (typeof detail === 'string' && detail) return detail;
    } catch {
      // A non-JSON response keeps the ordinary status/body message.
    }
  }
  return `${res.status} ${text || res.statusText}`;
}

/**
 * Fetch with session expiry tied to the credentials actually sent. A delayed
 * anonymous request or a request using an older token must never erase a
 * session established while it was in flight. JSON, downloads, and streams
 * share this transport so they apply the same rule.
 */
export async function fetchWithSession(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const authorization = new Headers(init?.headers).get('Authorization');
  const res = await fetch(url, init);
  const currentToken = getAccessToken();
  if (
    res.status === 401 &&
    currentToken &&
    authorization === `Bearer ${currentToken}`
  ) {
    clearAccessToken();
  }
  return res;
}

export async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new HttpError(await responseErrorMessage(res), res.status);
  }
  return (await res.json()) as T;
}

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetchWithSession(`${API_BASE_URL}${path}`, init);
  return parseJson<T>(res);
}

/** Unwrap a named field of a JSON response envelope. */
export async function fetchField<K extends string, T>(
  path: string,
  field: K,
  init?: RequestInit,
): Promise<T> {
  const data = await fetchJson<Record<K, T>>(path, init);
  return data[field];
}

/** Public endpoints omit identity; scoped endpoints opt in. */
export function jsonRequest(
  body: unknown,
  includeClientId = false,
): RequestInit & {headers: Record<string, string>} {
  return {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(includeClientId ? clientHeaders() : {}),
    },
    body: JSON.stringify(body),
  };
}

/** Parse complete SSE frames while retaining a trailing partial frame. */
export async function* readSseFrames<T>(res: Response): AsyncGenerator<T> {
  if (!res.ok || !res.body) throw new Error(await responseErrorMessage(res));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  for (;;) {
    const {done, value} = await reader.read();
    pending += decoder.decode(value, {stream: !done});
    const frames = pending.split('\n\n');
    pending = frames.pop() || '';
    for (const frame of frames) {
      const data = frame
        .split('\n')
        .find(line => line.startsWith('data: '))
        ?.slice(6);
      if (data) yield JSON.parse(data) as T;
    }
    if (done) break;
  }
}

/** Stream a model-backed JSON request with caller identity and BYOK headers. */
export async function* streamJson<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
  method = 'POST',
): AsyncGenerator<T> {
  const init = jsonRequest(body, true);
  const res = await fetchWithSession(`${API_BASE_URL}${path}`, {
    ...init,
    method,
    signal,
    headers: {...init.headers, ...byokHeaders()},
  });
  yield* readSseFrames<T>(res);
}

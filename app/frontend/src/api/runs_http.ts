// Shared HTTP and auth primitives for the API clients under `src/api/`.
// Extracted from `./runs`, which re-exports the public helpers so callers
// keep importing them from '@/api/runs'.

import {clearAccessToken, getAccessToken, getClientId} from '@/lib/client_id';
import {getStoredApiKey, getStoredApiProvider} from '@/lib/api_key';

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

/**
 * Header identifying the calling browser client to the backend. Exported for
 * sibling API clients so the auth-header policy stays defined once.
 */
export function clientHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token
    ? {Authorization: `Bearer ${token}`}
    : {'X-Client-ID': getClientId()};
}

/**
 * Bring-your-own-key headers for run creation and the interview/Q&A paths.
 * Sent as request headers, never query parameters (URLs leak into history,
 * logs, and referrers). Empty when no key is stored, so spreading is a
 * no-op for runs that use the deployment credential. The backend validates
 * the pair live and stores the key encrypted for the run's lifetime.
 */
export function byokHeaders(): Record<string, string> {
  const apiKey = getStoredApiKey();
  if (!apiKey) return {};
  return {
    'X-LLM-API-Key': apiKey,
    'X-LLM-Provider': getStoredApiProvider(),
  };
}

/**
 * A fetch failure carrying the response's HTTP status, for the rare caller
 * that must act on the status rather than just display the message (e.g.
 * distinguishing a 409 "someone else already resolved this" from any other
 * failure). Extends `Error` with the same message every other caller's
 * `instanceof Error` / `.message` handling already expects, so this is a
 * transparent upgrade of what `parseJson`/`assertOk` threw before.
 */
export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

/**
 * Builds the error message for a non-ok response: a clearer message for an
 * empty-bodied 500 (the API process itself is typically unreachable, e.g.
 * cold start or a proxy with no upstream, rather than a handled application
 * error), else the caller's prefix, else the raw status and body.
 */
function responseErrorMessage(
  status: number,
  statusText: string,
  text: string,
  errorPrefix?: string,
): string {
  if (status === 500 && !text.trim()) return 'API unavailable';
  if (errorPrefix) return `${errorPrefix} ${status}`;
  return `${status} ${text || statusText}`;
}

/**
 * Drop the stored researcher session on a 401. The token is expired or invalid,
 * so keeping it makes `clientHeaders` re-send a dead Bearer on every request —
 * each one 401s and the tab is bricked until sessionStorage is cleared by hand.
 * Dropping it lets the next request fall back to X-Client-ID. Called from every
 * response path that inspects status (plain JSON, SSE streams, raw requests).
 */
export function forgetSessionIfUnauthorized(res: Response): void {
  if (res.status === 401) clearAccessToken();
}

/**
 * Parses a fetch `Response` as JSON, or throws a descriptive `Error` when the
 * response was not ok.
 */
export async function parseJson<T>(
  res: Response,
  errorPrefix?: string,
): Promise<T> {
  if (!res.ok) {
    forgetSessionIfUnauthorized(res);
    const text = await res.text().catch(() => res.statusText);
    throw new HttpError(
      responseErrorMessage(res.status, res.statusText, text, errorPrefix),
      res.status,
    );
  }
  return (await res.json()) as T;
}

/**
 * Throws the same descriptive `Error` as `parseJson` when a response was not
 * ok, without touching the body. For requests whose success case carries no
 * JSON to parse (e.g. a 204 from a DELETE), where `parseJson` would throw on
 * the absent body after the request in fact succeeded.
 */
export async function assertOk(
  res: Response,
  errorPrefix?: string,
): Promise<void> {
  if (res.ok) return;
  forgetSessionIfUnauthorized(res);
  const text = await res.text().catch(() => res.statusText);
  throw new HttpError(
    responseErrorMessage(res.status, res.statusText, text, errorPrefix),
    res.status,
  );
}

/**
 * Fetches `path` relative to the API base URL and parses the JSON body.
 * Exported for sibling API clients (e.g. `@/api/system`) so the base-URL
 * and error-shaping policy stays defined once.
 */
export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, init);
  return parseJson<T>(res, errorPrefix);
}

/**
 * Fetches a `{[field]: T}` envelope and unwraps the named field.
 *
 * @param path Request path.
 * @param field Response key to unwrap.
 * @param init Optional fetch options (e.g. client headers).
 * @param errorPrefix Optional prefix for error messages.
 * @returns The unwrapped value.
 */
export async function fetchField<K extends string, T>(
  path: string,
  field: K,
  init?: RequestInit,
  errorPrefix?: string,
): Promise<T> {
  const data = await fetchJson<Record<K, T>>(path, init, errorPrefix);
  return data[field];
}

/**
 * Builds a JSON POST `RequestInit`. `includeClientId` is opt-in because only
 * endpoints that scope data by owning client (e.g. creating/listing runs)
 * need the `X-Client-ID` header.
 */
export function jsonRequest(
  body: unknown,
  includeClientId = false,
): RequestInit {
  return {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(includeClientId ? clientHeaders() : {}),
    },
    body: JSON.stringify(body),
  };
}

/**
 * Resolves to the response's readable body once it is confirmed live, or
 * throws a descriptive error for a non-OK or bodyless response.
 */
async function getSseBody(
  res: Response,
  errorPrefix?: string,
): Promise<ReadableStream<Uint8Array>> {
  if (res.ok && res.body) return res.body;
  forgetSessionIfUnauthorized(res);
  const text = await res.text().catch(() => res.statusText);
  throw new Error(
    responseErrorMessage(res.status, res.statusText, text, errorPrefix),
  );
}

/** Extracts the `data: ...` payload from one raw SSE frame, if present. */
function parseSseFrameData(frame: string): string | undefined {
  return frame
    .split('\n')
    .find(line => line.startsWith('data: '))
    ?.slice(6);
}

/**
 * Splits newly buffered text into complete `\n\n`-terminated frames plus
 * whatever trailing partial frame remains buffered until its terminator
 * arrives.
 */
function splitSseFrames(pending: string): {
  frames: string[];
  rest: string;
} {
  const frames = pending.split('\n\n');
  const rest = frames.pop() || '';
  return {frames, rest};
}

/**
 * Yields each `data:` payload of an SSE response body as it arrives.
 *
 * @param res A streaming response; a non-OK status throws before any frame.
 * @param errorPrefix Prefix for the thrown non-OK error message.
 */
export async function* readSseFrames<T>(
  res: Response,
  errorPrefix?: string,
): AsyncGenerator<T> {
  const body = await getSseBody(res, errorPrefix);
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  for (;;) {
    const {done, value} = await reader.read();
    pending += decoder.decode(value, {stream: !done});
    const {frames, rest} = splitSseFrames(pending);
    pending = rest;
    for (const frame of frames) {
      const data = parseSseFrameData(frame);
      if (data) yield JSON.parse(data) as T;
    }
    if (done) break;
  }
}

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
    id = crypto.randomUUID();
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

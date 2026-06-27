const KEY = 'co_scientist_client_id';

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

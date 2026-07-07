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

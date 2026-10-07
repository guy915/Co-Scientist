// A caught value's message for the user. Non-Error throws fall back to the
// caller's own wording, or to their string form.
export function errorMessage(error: unknown, fallback?: string): string {
  if (error instanceof Error) return error.message;
  return fallback ?? String(error);
}

// The HTTP status an API error carries, if any.
export function httpStatus(error: unknown): number | undefined {
  return error instanceof Error &&
    'status' in error &&
    typeof error.status === 'number'
    ? error.status
    : undefined;
}

import {rmSync} from 'node:fs';

/**
 * Removes the per-invocation run-state directory (SQLite DB, reports, cache)
 * created by {@link runStateDir}. Best-effort: a failed cleanup must not fail
 * the suite, and a fresh directory is minted next invocation regardless.
 */
export default function globalTeardown(): void {
  const dir = process.env.COSCI_E2E_STATE_DIR;
  if (!dir) return;
  try {
    rmSync(dir, {recursive: true, force: true});
  } catch {
    // Leaving a temp dir behind is harmless; never fail teardown over it.
  }
}

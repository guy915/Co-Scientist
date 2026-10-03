import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

// Absolute paths this harness pins so every launched process (uvicorn, vite)
// and the tests agree on where the app, its venv, and the isolated run state
// live regardless of the cwd Playwright is invoked from.
const HERE = dirname(fileURLToPath(import.meta.url));

/** Worktree root (the e2e/ dir sits directly under it). */
export const REPO_ROOT = resolve(HERE, '..', '..');

/** The FastAPI app package root (uvicorn's cwd; holds `app.main:app`). */
export const APP_DIR = join(REPO_ROOT, 'app');

/** The Vite frontend root (the dev server's cwd). */
export const FRONTEND_DIR = join(APP_DIR, 'frontend');

/** Python interpreter from the worktree venv `make setup` created. */
export const VENV_PYTHON = join(REPO_ROOT, '.venv', 'bin', 'python');

// Non-default ports so the harness never collides with a developer's running
// `make start` (which binds API 8008 / UI 5173 / MCP 8888).
export const API_PORT = Number(process.env.COSCI_E2E_API_PORT ?? 8108);
export const UI_PORT = Number(process.env.COSCI_E2E_UI_PORT ?? 5273);

export const API_URL = `http://127.0.0.1:${API_PORT}`;
export const UI_URL = `http://127.0.0.1:${UI_PORT}`;

// Deterministic credentials for the isolated browser-test API only.
export const E2E_RESEARCHER_ID = 'e2e-client';
export const E2E_RESEARCHER_ACCESS_CODE = 'e2e-researcher-access-code';
export const E2E_OTHER_RESEARCHER_ACCESS_CODE = 'e2e-other-access-code';
export const E2E_AUTH_SECRET = 'e2e-only-signing-secret';

/**
 * Resolves the per-invocation temp directory holding this run's SQLite DB,
 * reports, and cache. Created fresh on first call and stashed in the
 * environment so the Playwright config, the launched servers, and
 * globalTeardown all agree on the same isolated location — a new directory
 * each `make e2e` invocation keeps the "passes twice from a clean state"
 * determinism check honest (run 2 never inherits run 1's owned/cancelled runs).
 */
export function runStateDir(): string {
  const existing = process.env.COSCI_E2E_STATE_DIR;
  if (existing) return existing;
  const dir = mkdtempSync(join(tmpdir(), 'cosci-e2e-'));
  process.env.COSCI_E2E_STATE_DIR = dir;
  return dir;
}


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

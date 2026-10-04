import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

// Absolute harness paths keep servers and tests aligned regardless of
// invocation cwd.
const HERE = dirname(fileURLToPath(import.meta.url));

export const REPO_ROOT = resolve(HERE, '..', '..');

export const APP_DIR = join(REPO_ROOT, 'app');

export const FRONTEND_DIR = join(APP_DIR, 'frontend');

export const VENV_PYTHON = join(REPO_ROOT, '.venv', 'bin', 'python');

// Use separate ports to avoid colliding with make start.
export const API_PORT = Number(process.env.COSCI_E2E_API_PORT ?? 8108);
export const UI_PORT = Number(process.env.COSCI_E2E_UI_PORT ?? 5273);

export const API_URL = `http://127.0.0.1:${API_PORT}`;
export const UI_URL = `http://127.0.0.1:${UI_PORT}`;

// These deterministic credentials belong only to the isolated browser-test API.
export const E2E_RESEARCHER_ID = 'e2e-client';
export const E2E_RESEARCHER_ACCESS_CODE = 'e2e-researcher-access-code';
export const E2E_OTHER_RESEARCHER_ACCESS_CODE = 'e2e-other-access-code';
export const E2E_AUTH_SECRET = 'e2e-only-signing-secret';

// One fresh directory per invocation is shared through the environment with
// servers and teardown.
export function runStateDir(): string {
  const existing = process.env.COSCI_E2E_STATE_DIR;
  if (existing) return existing;
  const dir = mkdtempSync(join(tmpdir(), 'cosci-e2e-'));
  process.env.COSCI_E2E_STATE_DIR = dir;
  return dir;
}


// Cleanup failures cannot invalidate a passing suite; the next invocation gets
// fresh state.
export default function globalTeardown(): void {
  const dir = process.env.COSCI_E2E_STATE_DIR;
  if (!dir) return;
  try {
    rmSync(dir, {recursive: true, force: true});
  } catch {
    // Leaving a temp dir behind is harmless; never fail teardown over it.
  }
}

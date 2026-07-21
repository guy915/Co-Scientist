import {defineConfig, devices} from '@playwright/test';
import {
  API_PORT,
  API_URL,
  APP_DIR,
  FRONTEND_DIR,
  runStateDir,
  UI_PORT,
  UI_URL,
  VENV_PYTHON,
} from './support/paths';

// Resolve the isolated run-state directory once, up front, so both launched
// servers and globalTeardown share the exact same SQLite DB / reports / cache
// location (see runStateDir for why it is unique per invocation).
const STATE_DIR = runStateDir();

// The FastAPI backend, pinned to the deterministic offline mock workflow and
// an isolated on-disk store. Startup seeds three mock demo runs before the
// port answers /health, so allow a generous boot window.
const backendServer = {
  command: `${VENV_PYTHON} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
  cwd: APP_DIR,
  url: `${API_URL}/health`,
  timeout: 120_000,
  reuseExistingServer: false,
  stdout: 'pipe' as const,
  stderr: 'pipe' as const,
  env: {
    PATH: process.env.PATH ?? '',
    // Force the deterministic offline backend even if a provider key leaks in
    // from the environment: no network, reproducible content, no API budget
    // spent.
    COSCIENTIST_FORCE_OFFLINE: '1',
    // Isolated, per-invocation store so runs never touch a developer's DB and
    // the "passes twice from clean state" check starts fresh each time.
    COSCIENTIST_DB_PATH: `${STATE_DIR}/coscientist.db`,
    COSCIENTIST_REPORTS_DIR: `${STATE_DIR}/reports`,
    COSCIENTIST_CACHE_DIR: `${STATE_DIR}/cache`,
    // The frontend talks to this backend cross-origin (different port), so the
    // exact UI origin must be on the CORS allowlist — Starlette's wildcard
    // default withholds the Allow-Origin header once credentials are enabled.
    ALLOWED_ORIGINS: UI_URL,
    // No literature MCP server in the harness; the nodes fall back to
    // LLM-only, which the mock provider never exercises anyway.
    MCP_SERVER_URL: 'http://127.0.0.1:9/mcp',
  },
};

// The Vite dev server, pointed straight at the isolated backend via
// VITE_API_BASE_URL. Going direct (rather than through Vite's proxy) keeps the
// SSE event stream browser->backend with no proxy in the path, which is the
// most reliable arrangement for long-lived streaming responses. The backend's
// CORS allowlist is wildcard by default, so the cross-origin fetch/EventSource
// calls are permitted.
const frontendServer = {
  command: `bunx vite --port ${UI_PORT} --strictPort --host 127.0.0.1`,
  cwd: FRONTEND_DIR,
  url: UI_URL,
  timeout: 120_000,
  reuseExistingServer: false,
  stdout: 'pipe' as const,
  stderr: 'pipe' as const,
  env: {
    PATH: process.env.PATH ?? '',
    VITE_API_BASE_URL: API_URL,
  },
};

export default defineConfig({
  testDir: './tests',
  // One shared, stateful backend: run serially so runs created by the
  // create/cancel flows never leak into the home-page assertions mid-flight.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', {open: 'never'}]] : 'list',
  globalTeardown: './support/global_teardown.ts',
  timeout: 60_000,
  expect: {timeout: 15_000},
  use: {
    baseURL: UI_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {name: 'chromium', use: {...devices['Desktop Chrome']}},
  ],
  webServer: [backendServer, frontendServer],
});

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

// Resolve one state directory so servers and teardown share the same isolated
// store.
const STATE_DIR = runStateDir();
const PRODUCTION = process.env.COSCI_E2E_PRODUCTION === '1';

const backendServer = {
  command:
    `${VENV_PYTHON} -m uvicorn app.main:app ` +
    `--host 127.0.0.1 --port ${API_PORT}`,
  cwd: APP_DIR,
  url: `${API_URL}/health`,
  timeout: 120_000,
  reuseExistingServer: false,
  stdout: 'pipe' as const,
  stderr: 'pipe' as const,
  env: {
    PATH: process.env.PATH ?? '',
    // Force offline operation even when environment credentials leak into the
    // harness.
    COSCIENTIST_FORCE_OFFLINE: '1',
    PYTHON_DOTENV_DISABLED: '1',
    EVIDENCE_RESOLVER: 'offline',
    // A shared fake-provider store spans the whole browser suite. Exhaustion
    // and restart accounting are covered by the isolated admission tests.
    APP_LLM_GLOBAL_CALLS_PER_DAY: '8192',
    APP_LLM_GLOBAL_TOKENS_PER_DAY: '256000000',
    PROVIDER_HOST_CALLS_PER_DAY: '8192',
    PROVIDER_HOST_TOKENS_PER_DAY: '256000000',
    ANONYMOUS_SESSIONS_PER_HOST_PER_DAY: '256',
    RUNS_PER_HOST_PER_DAY: '500',
    RUNS_PER_DAY: '500',
    SMTP_HOST: '',
    // Fresh per-invocation stores must never touch developer data or inherit
    // earlier runs.
    COSCIENTIST_DB_PATH: `${STATE_DIR}/coscientist.db`,
    // Credentialed cross-origin requests require the exact UI origin on the
    // CORS allowlist.
    ALLOWED_ORIGINS: UI_URL,
    MCP_SERVER_URL: 'http://127.0.0.1:9/mcp',
  },
};

// Direct browser-to-backend SSE avoids proxy interference with long-lived
// streams.
const frontendServer = {
  // Vite embeds VITE_API_BASE_URL at build time; preview-only configuration is
  // too late.
  command: PRODUCTION
    ? `bun run build && bunx vite preview --port ${UI_PORT} --strictPort --host 127.0.0.1`
    : `bunx vite --port ${UI_PORT} --strictPort --host 127.0.0.1`,
  cwd: FRONTEND_DIR,
  url: UI_URL,
  timeout: 120_000,
  reuseExistingServer: false,
  stdout: 'pipe' as const,
  stderr: 'pipe' as const,
  env: {
    PATH: process.env.PATH ?? '',
    VITE_API_BASE_URL: API_URL,
    // Keep the test API URL out of the developer's normal dist artifact.
    COSCI_FRONTEND_DIST: PRODUCTION ? `${STATE_DIR}/frontend-dist` : 'dist',
  },
};

export default defineConfig({
  testDir: PRODUCTION ? './production' : './tests',
  // Stateful shared servers run serially so mutation flows cannot contaminate
  // home assertions.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', {open: 'never'}]] : 'list',
  globalTeardown: './support/paths.ts',
  timeout: 60_000,
  expect: {timeout: 15_000},
  use: {
    baseURL: UI_URL,
    launchOptions: {
      executablePath: process.env.COSCI_E2E_CHROMIUM_EXECUTABLE || undefined,
    },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
  webServer: [backendServer, frontendServer],
});

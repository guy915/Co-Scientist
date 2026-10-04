import {defineConfig, devices} from '@playwright/test';
import {
  API_PORT,
  API_URL,
  APP_DIR,
  E2E_AUTH_SECRET,
  E2E_OTHER_RESEARCHER_ACCESS_CODE,
  E2E_RESEARCHER_ACCESS_CODE,
  E2E_RESEARCHER_ID,
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
    CLAIM_ASSESSOR: 'heuristic',
    EVIDENCE_RESOLVER: 'offline',
    SMTP_HOST: '',
    // Fresh per-invocation stores must never touch developer data or inherit
    // earlier runs.
    COSCIENTIST_DB_PATH: `${STATE_DIR}/coscientist.db`,
    COSCIENTIST_CACHE_DIR: `${STATE_DIR}/cache`,
    AUTH_SECRET: E2E_AUTH_SECRET,
    AUTH_MODE: PRODUCTION ? 'required' : 'compatibility',
    RESEARCHER_ACCESS_CODES: JSON.stringify({
      [E2E_RESEARCHER_ID]: E2E_RESEARCHER_ACCESS_CODE,
      'e2e-other': E2E_OTHER_RESEARCHER_ACCESS_CODE,
    }),
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
  projects: [
    {name: 'chromium', use: {...devices['Desktop Chrome']}},
  ],
  webServer: [backendServer, frontendServer],
});

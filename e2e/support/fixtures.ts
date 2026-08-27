import {fileURLToPath} from 'node:url';

import {
  type APIRequestContext,
  type APIResponse,
  type Page,
  expect,
  request,
  test as base,
} from '@playwright/test';
import {API_URL} from './paths';

// A fixed owner id shared by the browser and every direct backend call. The
// frontend persists this under `co_scientist_client_id` in localStorage and
// sends it as `X-Client-ID`; the backend scopes "owned" runs by exact match.
// Seeding it (rather than reading back the app's random UUID) lets a run
// created over the API appear in the same browser's recents/home.
export const CLIENT_ID = 'e2e-client';

// localStorage key the frontend reads the client id from (see
// app/frontend/src/lib/client_id.ts).
const CLIENT_ID_KEY = 'co_scientist_client_id';

/**
 * Thin backend client used by flows that must set up or drive run state
 * outside the UI (there is no in-product affordance to create a run over the
 * API with tuned knobs, nor to cancel a running one). Every call carries the
 * shared `X-Client-ID`, so runs it creates are owned by the browser session.
 */
export interface BackendApi {
  createRun(body: Record<string, unknown>): Promise<{id: string}>;
  startRun(id: string): Promise<void>;
  cancelRun(id: string): Promise<void>;
  getRun(id: string): Promise<{status: string; [k: string]: unknown}>;
  listDemoRuns(): Promise<{id: string; research_goal: string}[]>;
}

// Runs one backend call, throwing a labelled error on any non-2xx so a
// failed setup call surfaces the status + body here instead of as a cryptic
// downstream assertion.
async function send(
  label: string,
  call: () => Promise<APIResponse>,
): Promise<APIResponse> {
  const res = await call();
  if (!res.ok()) {
    throw new Error(`${label} failed: ${res.status()} ${await res.text()}`);
  }
  return res;
}

function makeBackendApi(ctx: APIRequestContext): BackendApi {
  return {
    async createRun(body) {
      const res = await send('createRun', () =>
        ctx.post('/api/runs', {data: body}),
      );
      return (await res.json()) as {id: string};
    },
    async startRun(id) {
      await send('startRun', () =>
        ctx.post(`/api/runs/${id}/start`, {data: {}}),
      );
    },
    async cancelRun(id) {
      await send('cancelRun', () =>
        ctx.post(`/api/runs/${id}/cancel`, {data: {}}),
      );
    },
    async getRun(id) {
      const res = await send('getRun', () => ctx.get(`/api/runs/${id}`));
      return (await res.json()) as {status: string};
    },
    async listDemoRuns() {
      const res = await send('listDemoRuns', () => ctx.get('/api/runs/demo'));
      const payload = (await res.json()) as {
        runs: {id: string; research_goal: string}[];
      };
      return payload.runs;
    },
  };
}

/**
 * Test fixtures:
 * - `page` is pre-seeded with the shared client id before any app script runs,
 *   so the browser and API-created runs share one owner.
 * - `api` is a backend client (direct to the FastAPI port) tagged with the
 *   same client id.
 */
export const test = base.extend<{api: BackendApi}>({
  page: async ({page}, use) => {
    await page.addInitScript(
      ([clientKey, id]) => {
        window.localStorage.setItem(clientKey, id);
      },
      [CLIENT_ID_KEY, CLIENT_ID] as const,
    );
    await use(page);
  },
  api: async ({}, use) => {
    const ctx = await request.newContext({
      baseURL: API_URL,
      extraHTTPHeaders: {'X-Client-ID': CLIENT_ID},
    });
    await use(makeBackendApi(ctx));
    await ctx.dispose();
  },
});

export {expect};

/** A canvas size the visual-acceptance suite renders and screenshots at. */
export interface Viewport {
  width: number;
  height: number;
}

/** The desktop canvas the faithful-render acceptance shots are taken at. */
export const DESKTOP_VIEWPORT: Viewport = {width: 1440, height: 720};

/** The mobile canvas the faithful-render acceptance shots are taken at. */
export const MOBILE_VIEWPORT: Viewport = {width: 390, height: 780};

// Screenshots are build artifacts, not tracked docs assets: write them under
// e2e/test-results/, which e2e/.gitignore already covers, so a local run never
// leaves untracked PNGs in docs/assets/ for a later `git add -A` to pick up.
function assetPath(name: string): string {
  return fileURLToPath(new URL(`../test-results/${name}`, import.meta.url));
}

/**
 * Asserts the document does not scroll horizontally at `width`. Callers pass
 * the width from the same `Viewport` they sized the page with, so the sized
 * viewport and the asserted width cannot drift apart.
 */
export async function assertNoHorizontalOverflow(
  page: Page,
  width: number,
): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    width,
  );
}

/**
 * Asserts no horizontal overflow at the given viewport, then writes the
 * viewport-sized acceptance screenshot under e2e/test-results/.
 */
export async function captureViewport(
  page: Page,
  opts: Viewport & {name: string},
): Promise<void> {
  await assertNoHorizontalOverflow(page, opts.width);
  await page.screenshot({path: assetPath(opts.name), fullPage: false});
}

/**
 * Creates a run over the API, starts it, and waits for it to settle as
 * `completed` — the setup every check that needs a finished Goal Report to
 * render must do first.
 */
export async function createCompletedRun(
  api: BackendApi,
  body: Record<string, unknown>,
): Promise<string> {
  const {id} = await api.createRun(body);
  await api.startRun(id);
  await expect
    .poll(async () => (await api.getRun(id)).status)
    .toBe('completed');
  return id;
}

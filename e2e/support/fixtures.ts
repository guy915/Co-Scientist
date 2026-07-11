import {
  type APIRequestContext,
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
}

function makeBackendApi(ctx: APIRequestContext): BackendApi {
  return {
    async createRun(body) {
      const res = await ctx.post('/api/runs', {data: body});
      if (!res.ok()) {
        throw new Error(`createRun failed: ${res.status()} ${await res.text()}`);
      }
      return (await res.json()) as {id: string};
    },
    async startRun(id) {
      const res = await ctx.post(`/api/runs/${id}/start`, {data: {}});
      if (!res.ok()) {
        throw new Error(`startRun failed: ${res.status()} ${await res.text()}`);
      }
    },
    async cancelRun(id) {
      const res = await ctx.post(`/api/runs/${id}/cancel`, {data: {}});
      if (!res.ok()) {
        throw new Error(`cancelRun failed: ${res.status()} ${await res.text()}`);
      }
    },
    async getRun(id) {
      const res = await ctx.get(`/api/runs/${id}`);
      if (!res.ok()) {
        throw new Error(`getRun failed: ${res.status()} ${await res.text()}`);
      }
      return (await res.json()) as {status: string};
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
      ([key, id]) => {
        window.localStorage.setItem(key, id);
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

export {expect} from '@playwright/test';

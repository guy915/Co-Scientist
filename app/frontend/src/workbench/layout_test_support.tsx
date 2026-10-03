import {render} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {vi} from 'vitest';
import type {ChatSummary, Run} from '@/api/runs';
import {makeRun} from '@/test_fixtures';
import {resetSessionBaselineForTest} from './layout_diagnostics_state';
import {ChatHistoryProvider} from './hooks/chat_history_context';
import {RunHistoryProvider} from './hooks/run_history_context';
import {Layout} from './layout';
import {ThemeProvider} from './theme_context';

/**
 * Shared `@/api/runs` mock for the Layout test suites.
 *
 * Declared with `vi.hoisted` so it is available to the `vi.mock` factory
 * below, which is hoisted above this module's `Layout` import; routing every
 * suite's rendering through {@link renderLayout} guarantees the mock is
 * registered before the real `@/api/runs` module ever loads.
 */
const apiMock = vi.hoisted(() => {
  const listDemoRuns = vi.fn();
  const listRuns = vi.fn();
  const listInterviews = vi.fn();
  const getRunEvents = vi.fn();
  // Mirror the real loadRunHistory so tests keep driving history through the
  // listRuns/listDemoRuns mocks, while reusing the real merge policy.
  const loadRunHistory = vi.fn(async () => {
    const [owned, demo] = await Promise.all([
      listRuns().catch(() => []),
      listDemoRuns().catch(() => []),
    ]);
    const byId = new Map(
      ([...owned, ...demo] as Run[]).map(run => [run.id, run]),
    );
    return [...byId.values()].sort((a, b) => b.updated_at - a.updated_at);
  });
  return {
    listDemoRuns,
    listRuns,
    listInterviews,
    getRunEvents,
    loadRunHistory,
  };
});

const systemApiMock = vi.hoisted(() => ({getSystemStatus: vi.fn()}));

const logsApiMock = vi.hoisted(() => ({
  getAppLogs: vi.fn(),
  postAppLogs: vi.fn(),
  deleteAppLogs: vi.fn(),
  reportAppLogs: vi.fn(),
}));

// Spread the real module so pure helpers (isActiveStatus, ...) stay real and
// only the network calls are faked, matching chat_workspace_test_helpers.
vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  ...apiMock,
}));

vi.mock('@/api/system', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/system')>()),
  ...systemApiMock,
}));

// Spread the real module so constants (APP_LOGS_CHANGED_EVENT) stay real
// while the network calls are faked.
vi.mock('@/api/logs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/logs')>()),
  ...logsApiMock,
}));

export {apiMock, systemApiMock, logsApiMock};

/**
 * Renders the Layout shell inside the provider stack these suites assert on.
 *
 * @param path Initial router entry for the MemoryRouter.
 * @returns The React Testing Library render result.
 */
export function renderLayout(path = '/') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <ChatHistoryProvider>
          <RunHistoryProvider>
            <Layout>
              <main>Workspace content</main>
            </Layout>
          </RunHistoryProvider>
        </ChatHistoryProvider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

/**
 * Builds a run record shaped like the `/api/runs` list payload.
 *
 * @param id Run id.
 * @param goal Research goal text.
 * @returns A run record with a minimal summary.
 */
export function runFixture(id: string, goal: string) {
  return {
    ...makeRun({
      id,
      research_goal: goal,
      provider: 'mock',
      created_at: 1,
      updated_at: 2,
      completed_at: 3,
    }),
    summary: {events: 1, hypotheses: 1, evidence: 1, matches: 1, reviews: 1},
  };
}

/**
 * Builds a chat record shaped like the `/api/interviews` list payload.
 *
 * @param id Chat (interview) id.
 * @param challenge The scientist's opening research challenge.
 * @param overrides Fields to override, e.g. `title` or `run_id`.
 * @returns A chat summary record.
 */
export function chatFixture(
  id: string,
  challenge: string,
  overrides: Partial<ChatSummary> = {},
): ChatSummary {
  return {
    id,
    title: null,
    challenge,
    status: 'active',
    run_id: null,
    created_at: 1,
    updated_at: 2,
    ...overrides,
  };
}

/**
 * Resets globals/mocks and installs the default mock responses shared by every
 * Layout suite. Call from each suite's `beforeEach`.
 */
export function installLayoutMocks() {
  // Each suite is a fresh browsing session, so the diagnostics panel's
  // stored session baseline must not carry over between tests.
  resetSessionBaselineForTest();
  window.localStorage.clear();
  window.localStorage.setItem('cosci-theme', 'dark');
  document.documentElement.dataset.theme = '';
  document.documentElement.classList.remove('dark');
  apiMock.listRuns.mockResolvedValue([]);
  apiMock.listInterviews.mockResolvedValue([
    chatFixture(
      'chat-ferroptosis',
      'Generate testable hypotheses for ferroptosis in pancreatic cancer ' +
        'cells.',
    ),
  ]);
  apiMock.listDemoRuns.mockResolvedValue([
    runFixture(
      'demo-ferroptosis',
      'Generate testable hypotheses for ferroptosis in pancreatic cancer ' +
        'cells.',
    ),
  ]);
  apiMock.getRunEvents.mockReset();
  apiMock.getRunEvents.mockResolvedValue([]);
  logsApiMock.getAppLogs.mockReset();
  logsApiMock.getAppLogs.mockResolvedValue({
    logs: [],
    last_id: 0,
    total: 0,
    session_total: 0,
  });
  // The panel captures a session baseline on its first load and shows only
  // records added after it (so a refresh/reopen starts clean). This first
  // response establishes an empty baseline (id 0), so a suite's
  // own `mockResolvedValue` records — all with ids above 0 — are treated as
  // this-session records and rendered, matching the pre-baseline behavior.
  logsApiMock.getAppLogs.mockResolvedValueOnce({
    logs: [],
    last_id: 0,
    total: 0,
    session_total: 0,
  });
  logsApiMock.postAppLogs.mockReset();
  logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
  logsApiMock.deleteAppLogs.mockReset();
  logsApiMock.deleteAppLogs.mockResolvedValue({deleted: 0});
  logsApiMock.reportAppLogs.mockReset();
  logsApiMock.reportAppLogs.mockResolvedValue({status: 'sent', chars: 100});
  // Engine mode by default so the header status chip stays hidden and
  // pre-existing header assertions are unaffected.
  systemApiMock.getSystemStatus.mockReset();
  systemApiMock.getSystemStatus.mockResolvedValue({
    llm_backend: 'real',
    provider: 'engine',
    model_name: 'test/model',
  });
}

import {render} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {vi} from 'vitest';
import type {ChatSummary, Run} from '@/api/runs';
import {makeRun} from '@/test_fixtures';
import {resetSessionBaselineForTest} from './layout_diagnostics';
import {ChatHistoryProvider} from '@/shared/hooks/history_context';
import {RunHistoryProvider} from '@/shared/hooks/history_context';
import {Layout} from './layout';
import {ThemeProvider} from '@/shared/hooks/theme_context';

// Hoist mocks before imports bind real network modules.
const apiMock = vi.hoisted(() => {
  const listDemoRuns = vi.fn();
  const listRuns = vi.fn();
  const listInterviews = vi.fn();
  const getRunEvents = vi.fn();
  // Keep real merge policy while replacing only network methods.
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
}));

// Keep lifecycle helpers real so network mocks cannot change status semantics.
vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  ...apiMock,
}));

vi.mock('@/api/system', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/system')>()),
  ...systemApiMock,
}));

// Keep real log constants while replacing network calls.
vi.mock('@/api/logs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/logs')>()),
  ...logsApiMock,
}));

export {apiMock, systemApiMock, logsApiMock};

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

export function installLayoutMocks() {
  // Reset the session anchor so isolated suites cannot inherit log history.
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
  // Initial empty logs establish cursor zero; subsequent fixtures then belong
  // to this session.
  logsApiMock.getAppLogs.mockResolvedValueOnce({
    logs: [],
    last_id: 0,
    total: 0,
    session_total: 0,
  });
  logsApiMock.postAppLogs.mockReset();
  logsApiMock.postAppLogs.mockResolvedValue({added: 1, last_id: 1});
  systemApiMock.getSystemStatus.mockReset();
  systemApiMock.getSystemStatus.mockResolvedValue({
    llm_backend: 'real',
    provider: 'engine',
    model_name: 'test/model',
  });
}

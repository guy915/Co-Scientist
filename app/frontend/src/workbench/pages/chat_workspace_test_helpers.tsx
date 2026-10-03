import {render} from '@testing-library/react';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
import {vi} from 'vitest';
import type {ChatSummary, Run} from '@/api/runs';
import {makeHypothesis, makeRun} from '@/test_fixtures';
import {ChatHistoryProvider} from '../hooks/chat_history_context';
import {RunHistoryProvider} from '../hooks/run_history_context';
import {ChatWorkspace} from './chat_workspace';

/**
 * Shared `@/api/runs` mock for the ChatWorkspace test suites.
 *
 * Declared with `vi.hoisted` so it is available to the `vi.mock` factory
 * below, which is hoisted above this module's `ChatWorkspace` import; routing
 * every suite's rendering through {@link renderWorkspace} guarantees the mock
 * is registered before the real `@/api/runs` module ever loads.
 */
const apiMock = vi.hoisted(() => {
  const listDemoRuns = vi.fn();
  const listRuns = vi.fn();
  // Override the real loadRunHistory so tests keep driving history through the
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
    addInterviewTurn: vi.fn(),
    announceRunStart: vi.fn(),
    askRunQuestion: vi.fn(),
    createInterview: vi.fn(),
    createRun: vi.fn(),
    getHypotheses: vi.fn(),
    getRun: vi.fn(),
    getInterview: vi.fn(),
    getRunMessages: vi.fn(),
    listDemoRuns,
    listInterviews: vi.fn(async (): Promise<ChatSummary[]> => []),
    listRuns,
    loadRunHistory,
    startRun: vi.fn(),
  };
});

vi.mock('@/api/runs', async importOriginal => ({
  ...(await importOriginal<typeof import('@/api/runs')>()),
  ...apiMock,
}));

export {apiMock};

/**
 * Renders ChatWorkspace inside a MemoryRouter alongside a location probe so
 * tests can assert on the current pathname.
 *
 * @returns The React Testing Library render result.
 */
export function renderWorkspace(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RunHistoryProvider>
        <ChatHistoryProvider>
          <Routes>
            <Route path="/" element={<ChatWorkspace />} />
            <Route path="/chats/:id" element={<ChatWorkspace />} />
          </Routes>
          <LocationProbe />
        </ChatHistoryProvider>
      </RunHistoryProvider>
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

/**
 * Drives the connectors menu off a real /status payload. Only the connectors
 * list is read by the menu, so the rest of the response is left out. Must run
 * after installChatWorkspaceMocks, which clears stubbed globals.
 *
 * @param connectors The connector rows the stubbed /status returns.
 */
export function stubStatusConnectors(
  connectors: {id: string; display: string}[] = [
    {id: 'pubmed', display: 'PubMed'},
    {id: 'web_search', display: 'Web search'},
  ],
) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({connectors}),
      text: async () => '',
    })) as unknown as typeof fetch,
  );
}

/**
 * Builds a minimal run record, merging in any per-test overrides.
 *
 * @param overrides Fields to override on the base run record.
 * @returns A run record shaped like the `/api/runs` list payload.
 */
export function minimalRun(overrides = {}) {
  return {
    ...makeRun({
      id: 'run-1',
      research_goal: 'Investigate glucose homeostasis.',
      provider: 'mock',
      created_at: 1,
      updated_at: 2,
      completed_at: 3,
    }),
    top_elo: 1200,
    summary: {events: 4, hypotheses: 1, evidence: 1, matches: 1, reviews: 1},
    ...overrides,
  };
}

/** A representative hypothesis record returned by the getHypotheses mock. */
export const hypothesis = makeHypothesis({
  id: 'hyp-1',
  run_id: 'run-1',
  title: 'Mitochondrial feedback hypothesis',
  statement: 'A testable statement.',
  mechanism: 'Mitochondrial biogenesis rewires the feedback pathway.',
  expected_effect: 'A measurable effect.',
  experimental_context: 'An assay.',
  created_by_agent: 'generation',
  created_at: 1,
  elo_rating: 1240,
  win_count: 3,
  loss_count: 1,
});

/**
 * The Agent's start announcement in these suites -- deliberately nothing like
 * the standby copy the card falls back to, so a test asserting on it cannot
 * pass on hardcoded text.
 */
export const ANNOUNCEMENT_TEXT =
  'Your cold-stress session is running now. Look in on it whenever you ' +
  'like; the first ideas need a few minutes.';

/**
 * Resets globals/mocks and installs the default `@/api/runs` mock responses
 * shared by every ChatWorkspace suite. Call from each suite's `beforeEach`.
 */
export function installChatWorkspaceMocks() {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  apiMock.createRun.mockResolvedValue(minimalRun({status: 'draft'}));
  apiMock.createInterview.mockImplementation(async (goal: string) => ({
    id: 'interview-1',
    client_id: 'client-1',
    status: 'completed',
    fields: {
      research_challenge: goal,
      focus_area: ['Cold-stress glucose regulation'],
      preferences: ['Prioritize mechanistic novelty'],
      title: 'Cold-stress glucose homeostasis',
    },
    current_question: null,
    // Both turns, as the server records them: the session rebuilds its
    // transcript from this payload, and each bubble takes the durable turn
    // id it can be edited or retried by.
    turns: [
      {
        id: 1,
        role: 'user',
        content: goal,
        reasoning: null,
        fallback: false,
        created_at: 1,
      },
      {
        id: 2,
        role: 'agent',
        content: 'I have enough detail to configure this research run.',
        reasoning: 'Focus and constraints are both named, so this is ready.',
        fallback: false,
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: 2,
  }));
  apiMock.getHypotheses.mockResolvedValue([hypothesis]);
  apiMock.getRun.mockRejectedValue(new Error('Run not found'));
  // The Agent's reply to "Start research", as the server streams it: some
  // thinking, then the announcement itself. Suites asserting the degraded
  // card override this with a rejection.
  apiMock.announceRunStart.mockImplementation(
    async (
      _runId: string,
      _prompt: string,
      sinks: {
        onReasoning?: (fragment: string) => void;
        onChunk?: (fragment: string) => void;
      } = {},
    ) => {
      sinks.onReasoning?.('The plan is confirmed, so this is a confirmation.');
      sinks.onChunk?.(ANNOUNCEMENT_TEXT);
      return {fallback: false};
    },
  );
  apiMock.getRunMessages.mockResolvedValue([]);
  // Reset explicitly: restoreAllMocks leaves a mockResolvedValue set by
  // one test in place for the next, and a stray chat row carrying a
  // run_id changes what every later suite rehydrates.
  apiMock.listInterviews.mockResolvedValue([]);
  apiMock.listDemoRuns.mockResolvedValue([
    minimalRun({
      id: 'demo-ferroptosis',
      is_demo: true,
      research_goal:
        'What are the key molecular regulators of ferroptosis in pancreatic ' +
        'cancer cells, and how might their modulation enhance chemotherapy ' +
        'sensitivity?',
    }),
  ]);
  apiMock.listRuns.mockResolvedValue([]);
  apiMock.startRun.mockResolvedValue({id: 'run-1', status: 'queued'});
}

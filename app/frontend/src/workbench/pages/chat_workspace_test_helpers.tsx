import {render} from '@testing-library/react';
import {MemoryRouter, useLocation} from 'react-router-dom';
import {vi} from 'vitest';
import type {Run} from '@/api/runs';
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
    const {mergeByIdNewestFirst} = await import('@/lib/merge');
    return mergeByIdNewestFirst(
      [...owned, ...demo] as Run[],
      run => run.id,
      run => run.updated_at,
    );
  });
  return {
    createInterview: vi.fn(),
    createRun: vi.fn(),
    getHypotheses: vi.fn(),
    listDemoRuns,
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
export function renderWorkspace() {
  return render(
    <MemoryRouter>
      <RunHistoryProvider>
        <ChatWorkspace />
        <LocationProbe />
      </RunHistoryProvider>
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

/**
 * Builds a minimal run record, merging in any per-test overrides.
 *
 * @param overrides Fields to override on the base run record.
 * @returns A run record shaped like the `/api/runs` list payload.
 */
export function minimalRun(overrides = {}) {
  return {
    id: 'run-1',
    research_goal: 'Investigate glucose homeostasis.',
    profile: 'standard',
    status: 'completed',
    provider: 'mock',
    config: {},
    created_at: 1,
    updated_at: 2,
    completed_at: 3,
    error: null,
    top_elo: 1200,
    summary: {events: 4, hypotheses: 1, evidence: 1, matches: 1, reviews: 1},
    ...overrides,
  };
}

/** A representative hypothesis record returned by the getHypotheses mock. */
export const hypothesis = {
  id: 'hyp-1',
  run_id: 'run-1',
  parent_id: null,
  generation: 0,
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
  novelty_score: null,
  plausibility_score: null,
  testability_score: null,
  safety_status: null,
  status: null,
  cluster_id: null,
};

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
    turns: [
      {
        id: 1,
        role: 'agent',
        content: 'I have enough detail to configure this research run.',
        created_at: 2,
      },
    ],
    created_at: 1,
    updated_at: 2,
    completed_at: 2,
  }));
  apiMock.getHypotheses.mockResolvedValue([hypothesis]);
  apiMock.listDemoRuns.mockResolvedValue([
    minimalRun({
      id: 'demo-ferroptosis',
      is_demo: true,
      research_goal:
        'What are the key molecular regulators of ferroptosis in pancreatic cancer cells, and how might their modulation enhance chemotherapy sensitivity?',
    }),
  ]);
  apiMock.listRuns.mockResolvedValue([]);
  apiMock.startRun.mockResolvedValue({id: 'run-1', status: 'queued'});
}

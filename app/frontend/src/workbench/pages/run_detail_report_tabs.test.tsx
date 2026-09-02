import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {type Evidence, type RunWithSummary} from '@/api/runs';
import {makeRun, renderAt, tab} from './run_detail_test_support';

// Controllable stream mock: tests mutate `streamState` then rerender to drive
// the event-driven refetch effect. `setStream` replaces the events array so its
// identity changes and the effect re-runs.
const streamMock = vi.hoisted(() => ({
  state: {events: [] as {seq: number; type: string; payload: object}[]},
}));
vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({events: streamMock.state.events, terminal: false}),
}));

// Collapse the 600ms debounce to a synchronous passthrough with a stable
// identity, so a triggered refetch is observable in the same act() without
// timers. The wrapper is a module singleton (stable across renders); it always
// invokes the latest render's callback.
vi.mock('@/workbench/hooks/use_debounced_callback', () => {
  const latest: {fn: (...args: never[]) => void} = {fn: () => {}};
  const wrapper = Object.assign((...args: never[]) => latest.fn(...args), {
    cancel: () => {},
    flush: () => {},
  });
  return {
    useDebouncedCallback: (fn: (...args: never[]) => void) => {
      latest.fn = fn;
      return wrapper;
    },
  };
});

function setStream(events: {seq: number; type: string; payload: object}[]) {
  streamMock.state = {events};
}

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    getRun: vi.fn(),
    getHypotheses: vi.fn().mockResolvedValue([]),
    getEvidence: vi.fn().mockResolvedValue([]),
    getMatches: vi.fn().mockResolvedValue([]),
    getReviews: vi.fn().mockResolvedValue([]),
    getClaimEvidence: vi.fn().mockResolvedValue([]),
    getSafety: vi.fn().mockResolvedValue([]),
    adjudicateSafety: vi.fn().mockResolvedValue({
      decision_id: 1,
      resolution: 'approved',
    }),
    getCitations: vi.fn().mockResolvedValue([]),
    getReport: vi.fn().mockResolvedValue(null),
    sendRunSteering: vi
      .fn()
      .mockResolvedValue({id: 'message-1', status: 'queued'}),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  setStream([]);
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  // Reset per-run collection mocks so overrides do not leak between tests.
  vi.mocked(runsApi.getHypotheses).mockResolvedValue([]);
  vi.mocked(runsApi.getMatches).mockResolvedValue([]);
  vi.mocked(runsApi.getReport).mockResolvedValue(null);
  vi.mocked(runsApi.getSafety).mockResolvedValue([]);
});

it('renders all four report tabs', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  for (const label of [
    'Goal Details',
    'Learning',
    'Research Overview',
    'All Ideas',
  ]) {
    expect(tab(new RegExp(label))).toBeInTheDocument();
  }
});

it('marks the Goal Details tab active for the base URL', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  expect(tab(/^Goal Details$/)).toHaveAttribute('aria-current', 'page');
  expect(tab(/All Ideas/)).not.toHaveAttribute('aria-current');
});

it('resolves a tab alias in the URL to its canonical tab', async () => {
  // "specs" aliases to Goal Details.
  renderAt('/runs/run-1/specs');
  await screen.findByText('Run Specifications');
  expect(tab(/Goal Details/)).toHaveAttribute('aria-current', 'page');
});

it('activates the tab named directly in the URL', async () => {
  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');
  expect(tab(/Research Overview/)).toHaveAttribute('aria-current', 'page');
});

it('renders each tab as a link to its canonical route', async () => {
  // Anchors rather than buttons, so a middle- or cmd-click opens the tab in
  // a new browser tab.
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  expect(tab(/^Goal Details$/)).toHaveAttribute('href', '/runs/run-1/details');
  expect(tab(/Learning/)).toHaveAttribute('href', '/runs/run-1/learning');
  expect(tab(/Research Overview/)).toHaveAttribute(
    'href',
    '/runs/run-1/overview',
  );
  expect(tab(/All Ideas/)).toHaveAttribute('href', '/runs/run-1/ideas');
});

it('links to the canonical tab even from an aliased URL', async () => {
  // "specs" aliases to details; the nav never links back to the alias.
  renderAt('/runs/run-1/specs');
  await screen.findByText('All Ideas');
  expect(tab(/^Goal Details$/)).toHaveAttribute('href', '/runs/run-1/details');
});

it('navigates when a tab is clicked', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  fireEvent.click(tab(/Learning/));
  await waitFor(() =>
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/runs/run-1/learning',
    ),
  );
});

// The nav strip is a real <nav> of links, not a tablist, so the content
// region below it carries its own accessible name instead of an
// aria-controls/tabpanel relationship -- otherwise a screen-reader user
// landing in the region has no way to tell which section they arrived in.
it("labels the content region with the active tab's name", async () => {
  renderAt('/runs/run-1/overview');
  await screen.findByText('Summary');
  expect(
    screen.getByRole('main', {name: 'Research Overview'}),
  ).toBeInTheDocument();
});

const UNGROUNDED_NOTICE = /No literature was retrieved for this run/;

const EVIDENCE_ROW = {
  id: 'ev-1',
  title: 'Retrieved paper',
  source: 'pubmed',
  url: 'https://example.org/paper',
  authors: [],
  year: 2024,
  available: true,
  retracted: false,
} as Evidence;

// A completed run whose literature retrieval returned nothing still reads
// categorically unless flagged; offline-backed runs are illustrative
// fixtures and exempt (mirrors store.run_used_offline's exemption of the
// "Unverified" badge in GET /hypotheses).
it('flags a completed run with no retrieved evidence as ungrounded', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'real',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/details');

  expect(await screen.findByText(UNGROUNDED_NOTICE)).toBeInTheDocument();
});

it('shows the ungrounded notice on every report tab', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'real',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/ideas');

  expect(await screen.findByText(UNGROUNDED_NOTICE)).toBeInTheDocument();
});

it('omits the ungrounded notice when the run retrieved evidence', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'real',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([EVIDENCE_ROW]);

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
});

it('exempts offline-backed runs from the ungrounded notice', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'engine',
    llm_backend: 'offline',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
});

it('exempts legacy mock-provider runs from the ungrounded notice', async () => {
  // Rows created before the llm_backend column existed fall back to the
  // provider: the mock provider was always offline-backed.
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'mock',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
});

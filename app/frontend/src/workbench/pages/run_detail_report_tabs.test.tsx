import {resetRunDetailMocks} from './run_detail_api_test_support';
import * as runsApi from '@/api/runs';
import {type Evidence, type RunWithSummary} from '@/api/runs';
import {clearAccessToken} from '@/lib/client_id';
import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {makeRun, renderAt, tab} from './run_detail_test_support';

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

it('resolves a tab alias in the URL to its canonical tab', async () => {
  renderAt('/runs/run-1/specs');
  await screen.findByText('Run Specifications');
  expect(tab(/Goal Details/)).toHaveAttribute('aria-current', 'page');
});

it('links to the canonical tab even from an aliased URL', async () => {
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

it.each([
  ['details', 'engine', 'real', []],
  ['ideas', 'engine', 'real', []],
])(
  'flags a completed run with no retrieved evidence as ungrounded on %s',
  async (tab, provider, llm_backend, evidence) => {
    vi.mocked(runsApi.getRun).mockResolvedValue({
      ...makeRun('Study pathway X'),
      provider,
      llm_backend,
    } as RunWithSummary);
    vi.mocked(runsApi.getEvidence).mockResolvedValue(evidence);

    renderAt(`/runs/run-1/${tab}`);

    expect(await screen.findByText(UNGROUNDED_NOTICE)).toBeInTheDocument();
  },
);

it.each([
  ['the run retrieved evidence', 'engine', 'real', [EVIDENCE_ROW]],
  ['it is offline-backed', 'engine', 'offline', []],
  // Pre-llm_backend rows use provider to identify offline provenance.
  ['it is a legacy mock-provider run', 'mock', undefined, []],
])(
  'omits the ungrounded notice when %s',
  async (_name, provider, llm_backend, evidence) => {
    vi.mocked(runsApi.getRun).mockResolvedValue({
      ...makeRun('Study pathway X'),
      provider,
      llm_backend,
    } as RunWithSummary);
    vi.mocked(runsApi.getEvidence).mockResolvedValue(evidence);

    renderAt('/runs/run-1/details');

    await screen.findByText('Run Specifications');
    expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
  },
);

beforeEach(() => {
  resetRunDetailMocks();
  clearAccessToken();
});

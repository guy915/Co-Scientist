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

it('marks the Goal Details tab active for the base URL', async () => {
  renderAt('/runs/run-1');
  await screen.findByText('All Ideas');
  expect(tab(/^Goal Details$/)).toHaveAttribute('aria-current', 'page');
  expect(tab(/All Ideas/)).not.toHaveAttribute('aria-current');
});

it('resolves a tab alias in the URL to its canonical tab', async () => {
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
  // Pre-llm_backend rows use provider to identify offline provenance.
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    provider: 'mock',
  } as RunWithSummary);
  vi.mocked(runsApi.getEvidence).mockResolvedValue([]);

  renderAt('/runs/run-1/details');

  await screen.findByText('Run Specifications');
  expect(screen.queryByText(UNGROUNDED_NOTICE)).toBeNull();
});

beforeEach(() => {
  resetRunDetailMocks();
  clearAccessToken();
});

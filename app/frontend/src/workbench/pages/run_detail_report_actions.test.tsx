import {fireEvent, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {type Report} from '@/api/runs';
import {makeRun, renderAt} from './run_detail_test_support';

// D12/D11: the completed-run report surface carries a Markdown download and
// a share-link manager. These tests drive the full RunDetail page so the
// controls' gating (completed + report present) is covered too.

// Controllable stream mock (same shape as run_detail.test.tsx).
const streamMock = vi.hoisted(() => ({
  state: {events: [] as {seq: number; type: string; payload: object}[]},
}));
vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({events: streamMock.state.events, terminal: false}),
}));

// Collapse the 600ms debounce to a synchronous passthrough.
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
    getCitations: vi.fn().mockResolvedValue([]),
    listInterviews: vi.fn().mockResolvedValue([]),
    getReport: vi.fn(),
    fetchReportMarkdown: vi.fn(),
    listReportShares: vi.fn().mockResolvedValue([]),
    createReportShare: vi.fn(),
    revokeReportShare: vi.fn().mockResolvedValue(undefined),
    sendRunSteering: vi
      .fn()
      .mockResolvedValue({id: 'message-1', status: 'queued'}),
  };
});

/** The persisted report object a completed run carries. */
const REPORT = {
  id: 'rep-1',
  run_id: 'run-1',
  payload: {leaderboard: []},
  created_at: 1,
};

/** Sentinel object URL returned by the stubbed `URL.createObjectURL`. */
const REPORT_BLOB_URL = 'blob:goal-report';

function installDownloadSpies() {
  const createObjectURL = vi.fn((blob: Blob) => {
    expect(blob).toBeInstanceOf(Blob);
    return REPORT_BLOB_URL;
  });
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: revokeObjectURL,
  });
  const downloadedNames: string[] = [];
  const anchorClick = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(function (this: HTMLAnchorElement) {
      downloadedNames.push(this.download);
    });
  return {createObjectURL, revokeObjectURL, downloadedNames, anchorClick};
}

function installClipboardSpy() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {writeText},
  });
  return writeText;
}

let spies: ReturnType<typeof installDownloadSpies>;

beforeEach(() => {
  vi.clearAllMocks();
  streamMock.state = {events: []};
  spies = installDownloadSpies();
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
  vi.mocked(runsApi.getReport).mockResolvedValue(REPORT as unknown as Report);
  vi.mocked(runsApi.fetchReportMarkdown).mockResolvedValue('# Goal report');
  vi.mocked(runsApi.listReportShares).mockResolvedValue([]);
  vi.mocked(runsApi.createReportShare).mockResolvedValue({
    id: 'share-1',
    run_id: 'run-1',
    token: 'tok-123',
    created_at: 1700000000,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Gating: the controls belong to a finished report only
// ---------------------------------------------------------------------------

it('shows download and share controls for a completed run with a report', async () => {
  renderAt('/runs/run-1/overview');

  expect(
    await screen.findByRole('button', {name: 'Download report'}),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('button', {name: 'Share report'}),
  ).toBeInTheDocument();
});

it('hides the controls while the run has no report yet', async () => {
  vi.mocked(runsApi.getReport).mockResolvedValue(null);

  renderAt('/runs/run-1/overview');

  // Wait for the settled tab content, then assert the controls stayed hidden.
  expect(await screen.findByText('Summary')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', {name: 'Download report'}),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', {name: 'Share report'}),
  ).not.toBeInTheDocument();
});

it('hides the controls for an in-flight run', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'running',
  });

  renderAt('/runs/run-1/overview');

  expect(await screen.findByText('Research in progress')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', {name: 'Download report'}),
  ).not.toBeInTheDocument();
});

it('hides the controls for a run that ended without a report', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue({
    ...makeRun('Study pathway X'),
    status: 'failed',
    error: 'boom',
  });

  renderAt('/runs/run-1/overview');

  expect(await screen.findByText('Run failed')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', {name: 'Download report'}),
  ).not.toBeInTheDocument();
});

// ---------------------------------------------------------------------------
// D12: Markdown download
// ---------------------------------------------------------------------------

it('downloads the report Markdown through an authenticated fetch', async () => {
  renderAt('/runs/run-1/overview');
  fireEvent.click(await screen.findByRole('button', {name: 'Download report'}));

  await waitFor(() => {
    expect(runsApi.fetchReportMarkdown).toHaveBeenCalledWith('run-1');
  });
  await waitFor(() => {
    expect(spies.anchorClick).toHaveBeenCalled();
  });
  expect(spies.createObjectURL).toHaveBeenCalledTimes(1);
  const blob = spies.createObjectURL.mock.calls[0][0];
  expect(blob).toBeInstanceOf(Blob);
  expect(blob.type).toBe('text/markdown;charset=utf-8');
  expect(spies.downloadedNames).toEqual(['study-pathway-x.md']);
  expect(spies.revokeObjectURL).toHaveBeenCalledWith(REPORT_BLOB_URL);
});

it('falls back to the run id when the title has no slug-worthy text', async () => {
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun(''));

  renderAt('/runs/run-1/overview');
  fireEvent.click(await screen.findByRole('button', {name: 'Download report'}));

  await waitFor(() => {
    expect(spies.downloadedNames).toEqual(['run-1.md']);
  });
});

it('toasts an error when the report vanished before the download', async () => {
  vi.mocked(runsApi.fetchReportMarkdown).mockResolvedValue(null);

  renderAt('/runs/run-1/overview');
  fireEvent.click(await screen.findByRole('button', {name: 'Download report'}));

  const message = await screen.findByText(/report is not available/i);
  expect(message.closest('[role="status"]')).not.toBeNull();
  expect(spies.anchorClick).not.toHaveBeenCalled();
});

it('toasts the error when the download request fails', async () => {
  vi.mocked(runsApi.fetchReportMarkdown).mockRejectedValue(
    new Error('500 boom'),
  );

  renderAt('/runs/run-1/overview');
  fireEvent.click(await screen.findByRole('button', {name: 'Download report'}));

  const message = await screen.findByText(/500 boom/);
  expect(message.closest('[role="status"]')).not.toBeNull();
  expect(spies.anchorClick).not.toHaveBeenCalled();
});

// ---------------------------------------------------------------------------
// D11: share-link management
// ---------------------------------------------------------------------------

async function openSharePanel() {
  renderAt('/runs/run-1/overview');
  fireEvent.click(await screen.findByRole('button', {name: 'Share report'}));
}

it('lists existing shares when the panel opens', async () => {
  vi.mocked(runsApi.listReportShares).mockResolvedValue([
    {id: 'share-9', run_id: 'run-1', created_at: 1700000000},
  ]);

  await openSharePanel();

  await waitFor(() => {
    expect(runsApi.listReportShares).toHaveBeenCalledWith('run-1');
  });
  expect(screen.getAllByRole('button', {name: 'Revoke link'})).toHaveLength(1);
});

it('shows an honest empty state when no links exist', async () => {
  await openSharePanel();

  expect(await screen.findByText(/no public links yet/i)).toBeInTheDocument();
});

it('creates a link and shows the public URL with a copy action', async () => {
  const writeText = installClipboardSpy();
  await openSharePanel();
  expect(await screen.findByText(/no public links yet/i)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', {name: 'Create public link'}));

  const expectedUrl = `${window.location.origin}/shared/tok-123`;
  const urlField = await screen.findByText(expectedUrl);
  expect(urlField).toBeInTheDocument();
  expect(runsApi.createReportShare).toHaveBeenCalledWith('run-1');

  fireEvent.click(screen.getByRole('button', {name: 'Copy link'}));
  await waitFor(() => {
    expect(writeText).toHaveBeenCalledWith(expectedUrl);
  });
});

it('keeps the new link out of the list until the server confirms it', async () => {
  await openSharePanel();
  expect(await screen.findByText(/no public links yet/i)).toBeInTheDocument();

  vi.mocked(runsApi.createReportShare).mockImplementation(
    () => new Promise(() => {}), // never resolves
  );
  fireEvent.click(screen.getByRole('button', {name: 'Create public link'}));

  // Still no share rows while the create is in flight.
  expect(screen.queryAllByRole('button', {name: 'Revoke link'})).toHaveLength(
    0,
  );
});

it('surfaces a creation failure inline instead of a silent no-op', async () => {
  vi.mocked(runsApi.createReportShare).mockRejectedValue(
    new Error('409 Goal Report not ready'),
  );
  await openSharePanel();

  fireEvent.click(
    await screen.findByRole('button', {name: 'Create public link'}),
  );

  expect(await screen.findByText(/goal report not ready/i)).toBeInTheDocument();
});

it('revokes a share and removes it without a reload', async () => {
  vi.mocked(runsApi.listReportShares).mockResolvedValue([
    {id: 'share-9', run_id: 'run-1', created_at: 1700000000},
  ]);
  await openSharePanel();
  const revokeButtons = await screen.findAllByRole('button', {
    name: 'Revoke link',
  });
  expect(revokeButtons).toHaveLength(1);

  fireEvent.click(revokeButtons[0]);

  await waitFor(() => {
    expect(runsApi.revokeReportShare).toHaveBeenCalledWith('run-1', 'share-9');
  });
  await waitFor(() => {
    expect(screen.queryAllByRole('button', {name: 'Revoke link'})).toHaveLength(
      0,
    );
  });
  expect(await screen.findByText(/no public links yet/i)).toBeInTheDocument();
});

it('clears the shown URL when its link is revoked', async () => {
  await openSharePanel();
  fireEvent.click(
    await screen.findByRole('button', {name: 'Create public link'}),
  );
  const expectedUrl = `${window.location.origin}/shared/tok-123`;
  expect(await screen.findByText(expectedUrl)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', {name: 'Revoke link'}));

  await waitFor(() => {
    expect(screen.queryByText(expectedUrl)).not.toBeInTheDocument();
  });
});

it('closes the panel on a click outside it', async () => {
  await openSharePanel();
  expect(await screen.findByText(/no public links yet/i)).toBeInTheDocument();

  fireEvent.pointerDown(document.body);

  await waitFor(() => {
    expect(screen.queryByText(/no public links yet/i)).not.toBeInTheDocument();
  });
});

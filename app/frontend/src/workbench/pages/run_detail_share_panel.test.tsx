import {render, screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import {ShareReportPanel} from './run_detail_share_panel';

// O4: this popover is a management panel with its own controls (create,
// revoke, copy), not status output -- `role="status"` wrongly made it an
// implicit live region that gets announced on open and re-announced on
// every change.

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    listReportShares: vi.fn(),
  };
});

beforeEach(() => {
  vi.mocked(runsApi.listReportShares).mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

it('names the panel for assistive tech instead of announcing it as status', async () => {
  render(<ShareReportPanel runId="run-1" />);

  expect(
    await screen.findByRole('dialog', {name: 'Share report'}),
  ).toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

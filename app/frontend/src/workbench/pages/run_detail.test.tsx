import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter, Route, Routes, useLocation} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import * as runsApi from '@/api/runs';
import type {RunWithSummary} from '@/api/runs';
import {RunDetail} from './run_detail';

vi.mock('@/hooks/use_run_stream', () => ({
  useRunStream: () => ({events: [], terminal: false}),
}));

vi.mock('@/api/runs', async importActual => {
  const actual = await importActual<typeof import('@/api/runs')>();
  return {
    ...actual,
    getRun: vi.fn(),
    getHypotheses: vi.fn().mockResolvedValue([]),
    getEvidence: vi.fn().mockResolvedValue([]),
    getMatches: vi.fn().mockResolvedValue([]),
    getReviews: vi.fn().mockResolvedValue([]),
    getCitations: vi.fn().mockResolvedValue([]),
    getReport: vi.fn().mockResolvedValue(null),
  };
});

const makeRun = (goal: string): RunWithSummary =>
  ({
    id: 'run-1',
    research_goal: goal,
    status: 'completed',
    config: {
      setup: {
        goal,
        requirements: ['Testable'],
        attributes: ['Novel'],
        criteria: ['Feasible'],
      },
    },
  }) as unknown as RunWithSummary;

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
        <Route path="/runs/:id/:tab" element={<RunDetail />} />
      </Routes>
      <LocationDisplay />
    </MemoryRouter>,
  );
}

const tab = (name: RegExp) => screen.getByRole('button', {name});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(runsApi.getRun).mockResolvedValue(makeRun('Study pathway X'));
});

describe('RunDetail', () => {
  it('shows a skeleton while loading, then the goal details', async () => {
    renderAt('/runs/run-1');
    expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
    expect(
      await screen.findByText('Research goal details'),
    ).toBeInTheDocument();
  });

  it('renders all four report tabs', async () => {
    renderAt('/runs/run-1');
    await screen.findByText('Research goal details');
    for (const label of [
      'Goal Details',
      'Learning',
      'Research Overview',
      'All Ideas',
    ]) {
      expect(tab(new RegExp(label))).toBeInTheDocument();
    }
  });

  it('marks the Details tab active for the base URL', async () => {
    renderAt('/runs/run-1');
    await screen.findByText('Research goal details');
    expect(tab(/Goal Details/)).toHaveAttribute('aria-current', 'page');
    expect(tab(/All Ideas/)).not.toHaveAttribute('aria-current');
  });

  it('resolves a tab alias in the URL to its canonical tab', async () => {
    // "specs" aliases to the details tab.
    renderAt('/runs/run-1/specs');
    await screen.findByText('Research goal details');
    expect(tab(/Goal Details/)).toHaveAttribute('aria-current', 'page');
  });

  it('activates the tab named directly in the URL', async () => {
    renderAt('/runs/run-1/overview');
    await screen.findByText('Research overview');
    expect(tab(/Research Overview/)).toHaveAttribute('aria-current', 'page');
  });

  it('navigates when a tab is clicked', async () => {
    renderAt('/runs/run-1');
    await screen.findByText('Research goal details');
    fireEvent.click(tab(/All Ideas/));
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/runs/run-1/ideas',
      ),
    );
  });

  it('applies the domain-specific title override', async () => {
    vi.mocked(runsApi.getRun).mockResolvedValue(
      makeRun('Reversing MASLD liver fibrosis'),
    );
    renderAt('/runs/run-1');
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: /MASH-associated liver fibrosis/i,
      }),
    ).toBeInTheDocument();
  });

  it('shows an error alert when loading fails', async () => {
    vi.mocked(runsApi.getRun).mockRejectedValue(new Error('boom'));
    renderAt('/runs/run-1');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('boom');
  });
});

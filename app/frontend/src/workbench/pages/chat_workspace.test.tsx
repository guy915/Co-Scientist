import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {ChatWorkspace} from './chat_workspace';

const apiMock = vi.hoisted(() => ({
  createRun: vi.fn(),
  getCitations: vi.fn(),
  getEvidence: vi.fn(),
  getHypotheses: vi.fn(),
  getMatches: vi.fn(),
  getReport: vi.fn(),
  getReviews: vi.fn(),
  getRun: vi.fn(),
  getSystemStatus: vi.fn(),
  listRuns: vi.fn(),
  sendMessage: vi.fn(),
  startRun: vi.fn(),
}));

const streamMock = vi.hoisted(() => ({
  useRunStream: vi.fn(),
}));

vi.mock('@/api/runs', () => apiMock);
vi.mock('@/hooks/use_run_stream', () => streamMock);

function renderWorkspace() {
  return render(
    <MemoryRouter>
      <ChatWorkspace />
    </MemoryRouter>,
  );
}

function minimalRun(overrides = {}) {
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
    summary: {events: 4, hypotheses: 1, evidence: 1, matches: 1, reviews: 1},
    ...overrides,
  };
}

const hypothesis = {
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

beforeEach(() => {
  apiMock.createRun.mockResolvedValue(minimalRun({status: 'draft'}));
  apiMock.getCitations.mockResolvedValue([
    {
      id: 1,
      hypothesis_id: 'hyp-1',
      evidence_id: 'ev-1',
      claim: 'Mechanistic claim',
      state: 'verified',
    },
  ]);
  apiMock.getEvidence.mockResolvedValue([
    {
      id: 'ev-1',
      title: 'Glucose homeostasis study',
      source: 'mock',
      url: '',
      authors: [],
      year: 2025,
      abstract: 'abstract',
      available: true,
    },
  ]);
  apiMock.getHypotheses.mockResolvedValue([hypothesis]);
  apiMock.getMatches.mockResolvedValue([
    {
      id: 1,
      iteration: 1,
      winner_id: 'hyp-1',
      loser_id: 'hyp-2',
      winner_elo_before: 1200,
      winner_elo_after: 1240,
      loser_elo_before: 1200,
      loser_elo_after: 1160,
      rationale: 'Stronger mechanistic specificity.',
      created_at: 1,
    },
  ]);
  apiMock.getReport.mockResolvedValue({
    id: 'report-1',
    run_id: 'run-1',
    payload: {
      research_goal: 'Investigate glucose homeostasis.',
      profile: 'standard',
      provider: 'mock',
      leaderboard: [{id: 'hyp-1', title: hypothesis.title, elo: 1240}],
    },
    markdown_path: '/tmp/report.md',
    created_at: 4,
  });
  apiMock.getReviews.mockResolvedValue([
    {
      id: 1,
      hypothesis_id: 'hyp-1',
      reviewer_agent: 'reflection',
      summary: 'High testability and clear mechanism.',
      critique: 'critique',
      novelty: 0.7,
      plausibility: 0.8,
      testability: 0.9,
      overall: 0.8,
    },
  ]);
  apiMock.getRun.mockResolvedValue(minimalRun());
  apiMock.getSystemStatus.mockResolvedValue({
    mcp_available: true,
    pubmed_available: true,
    literature_review_available: true,
    mcp_server_url: 'http://localhost:8888/mcp',
    provider: 'mock',
    mock_mode: true,
    has_provider_key: false,
    engine_importable: true,
    model_name: 'mock',
  });
  apiMock.listRuns.mockResolvedValue([]);
  apiMock.sendMessage.mockResolvedValue({id: 1});
  apiMock.startRun.mockResolvedValue({id: 'run-1', status: 'queued'});
  streamMock.useRunStream.mockReturnValue({
    events: [],
    lastSeq: 0,
    isOpen: false,
    error: null,
    terminal: true,
  });
});

describe('ChatWorkspace', () => {
  it('opens on a chat-first screen with the minimal sidebar', () => {
    renderWorkspace();

    expect(
      screen.getByRole('heading', {name: 'What should we investigate?'}),
    ).toBeInTheDocument();
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Base')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Describe a research goal...')).toBeInTheDocument();
  });

  it('infers a run spec in chat and starts the durable run on confirmation', async () => {
    renderWorkspace();

    const input = screen.getByPlaceholderText('Describe a research goal...');
    fireEvent.change(input, {
      target: {value: 'Investigate glucose homeostasis under cold stress.'},
    });
    fireEvent.submit(input.closest('form')!);

    expect(await screen.findByText('Inferred run setup')).toBeInTheDocument();
    expect(screen.getByText('Start this run?')).toBeInTheDocument();
    expect(screen.getByText('Standard hypothesis sprint')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Start'));

    await waitFor(() => {
      expect(apiMock.createRun).toHaveBeenCalledWith(
        expect.objectContaining({
          research_goal: 'Investigate glucose homeostasis under cold stress.',
          profile: 'standard',
        }),
      );
      expect(apiMock.startRun).toHaveBeenCalledWith('run-1');
    });

    expect(
      await screen.findByText('Mitochondrial feedback hypothesis'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Report ready').length).toBeGreaterThan(0);
  });

  it('opens a persistent explanation panel from why-this-ranked', async () => {
    renderWorkspace();

    const input = screen.getByPlaceholderText('Describe a research goal...');
    fireEvent.change(input, {target: {value: 'Investigate glucose control.'}});
    fireEvent.submit(input.closest('form')!);
    fireEvent.click(await screen.findByText('Start'));

    fireEvent.click(await screen.findByText('why this ranked'));

    expect(await screen.findByText('Why this ranked')).toBeInTheDocument();
    expect(screen.getByText('Rank signal')).toBeInTheDocument();
    expect(screen.getByText('Stronger mechanistic specificity.')).toBeInTheDocument();
  });
});

import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter, useLocation} from 'react-router-dom';
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
  askQuestionUrl: vi.fn(),
  listDemoRuns: vi.fn(),
  listMessages: vi.fn(),
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
      <LocationProbe />
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
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
  vi.unstubAllGlobals();
  apiMock.askQuestionUrl.mockImplementation(
    (runId: string) => `/api/runs/${runId}/messages/ask`,
  );
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
  apiMock.listDemoRuns.mockResolvedValue([
    minimalRun({
      id: 'demo-ferroptosis',
      is_demo: true,
      research_goal:
        'What are the key molecular regulators of ferroptosis in pancreatic cancer cells, and how might their modulation enhance chemotherapy sensitivity?',
    }),
  ]);
  apiMock.listMessages.mockResolvedValue([]);
  apiMock.listRuns.mockResolvedValue([]);
  apiMock.sendMessage.mockImplementation(
    (runId: string, content: string, kind = 'steering') =>
      Promise.resolve({
        id: 1,
        run_id: runId,
        sender: 'user',
        content,
        kind,
        created_at: Date.now() / 1000,
        applied: false,
        status: 'queued',
      }),
  );
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
  it('opens on the reference-style AI Co-Scientist home screen', async () => {
    renderWorkspace();

    expect(
      screen.getByRole('heading', {
        name: 'Drive novel scientific discovery with Co-Scientist.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('Recents')).toBeInTheDocument();
    expect(screen.getByText('Create a Research goal')).toBeInTheDocument();
    expect(screen.getByText('Generate hypotheses')).toBeInTheDocument();
    expect(screen.getByText('Evaluate and rank')).toBeInTheDocument();
    expect(screen.queryByText('AI Co-Scientist')).toBeNull();
    expect(
      screen.getByText('Start a new research goal to begin'),
    ).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(
      await screen.findByText(/ferroptosis in pancreatic cancer cells/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {
        name: /ferroptosis in pancreatic cancer cells/i,
      }),
    ).toHaveAttribute('href', '/runs/demo-ferroptosis/details');
  });

  it('shows four recent cards before loading the rest', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue(
      Array.from({length: 6}, (_, index) =>
        minimalRun({
          id: `run-${index + 1}`,
          research_goal: `Recent research question ${index + 1}`,
          created_at: index + 1,
          updated_at: index + 1,
          completed_at: index + 2,
        }),
      ),
    );

    renderWorkspace();

    expect(
      await screen.findAllByText('Recent research question 6'),
    ).not.toHaveLength(0);
    expect(screen.getAllByText('Recent research question 3')).not.toHaveLength(
      0,
    );
    expect(screen.queryByText('Recent research question 2')).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Load more'}));

    expect(screen.getAllByText('Recent research question 2')).not.toHaveLength(
      0,
    );
    expect(screen.getAllByText('Recent research question 1')).not.toHaveLength(
      0,
    );
    expect(screen.queryByRole('button', {name: 'Load more'})).toBeNull();
  });

  it('previews a suggestion without moving the composer', async () => {
    renderWorkspace();

    const composer = await screen.findByRole('textbox');
    const originalComposerTop = composer
      .closest('.reference-composer')
      ?.getBoundingClientRect().top;

    const suggestion = screen.getByRole('button', {
      name: 'Find new therapeutic targets for M.tuberculosis by combining...',
    });

    fireEvent.pointerEnter(suggestion);

    const preview = screen.getByText(
      'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
    );
    expect(preview).toBeInTheDocument();
    expect(preview).toHaveClass('visible');
    expect(preview.closest('.reference-suggestion-slot')).toContainElement(
      suggestion,
    );
    expect(
      composer.closest('.reference-composer')?.getBoundingClientRect().top,
    ).toBe(originalComposerTop);
  });

  it('infers a run spec in chat and starts the durable run on confirmation', async () => {
    renderWorkspace();

    const input = screen.getByRole('textbox');
    fireEvent.change(input, {
      target: {value: 'Investigate glucose homeostasis under cold stress.'},
    });
    fireEvent.submit(input.closest('form')!);

    expect(
      await screen.findByText(/Please review or edit the details below/),
    ).toBeInTheDocument();
    expect(screen.queryByText('AI Co-Scientist')).toBeNull();
    expect(
      screen.getByRole('heading', {name: 'Research plan'}),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Here's my plan to tackle the topic:"),
    ).toBeInTheDocument();
    expect(
      screen
        .getByRole('heading', {
          name: 'Investigate glucose homeostasis under cold stress',
        })
        .closest('.reference-setup-document'),
    ).not.toBeNull();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
    expect(screen.getByRole('group', {name: 'Focus'})).toBeInTheDocument();
    expect(screen.getByRole('group', {name: 'Tier'})).toBeInTheDocument();
    expect(screen.getByLabelText(/Balance/i)).toBeChecked();
    expect(screen.getByLabelText(/Standard/i)).toBeChecked();

    fireEvent.click(screen.getByLabelText(/Prefer novelty/i));
    fireEvent.click(screen.getByLabelText(/Extended/i));

    fireEvent.click(screen.getByText('Start research'));

    await waitFor(() => {
      expect(apiMock.createRun).toHaveBeenCalledWith(
        expect.objectContaining({
          research_goal: 'Investigate glucose homeostasis under cold stress.',
          requirements: expect.arrayContaining([
            expect.stringContaining('mechanistic novelty'),
          ]),
          attributes: expect.arrayContaining(['Mechanistically specific']),
          criteria: expect.arrayContaining(['Scientific soundness']),
          focus: 'prefer_novelty',
          tier: 'extended',
        }),
      );
      expect(apiMock.startRun).toHaveBeenCalledWith('run-1');
    });

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/runs/run-1/details',
      );
    });
    expect(screen.queryByText('Report ready')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Mitochondrial feedback hypothesis'),
    ).not.toBeInTheDocument();
  });

  it('fills the composer from a suggested prompt', () => {
    renderWorkspace();

    fireEvent.click(
      screen.getByText(
        'Find new therapeutic targets for M.tuberculosis by combining...',
      ),
    );

    expect(screen.getByRole('textbox')).toHaveValue(
      'Find new therapeutic targets for M.tuberculosis by combining host-pathogen interaction datasets with recent literature.',
    );
  });
});

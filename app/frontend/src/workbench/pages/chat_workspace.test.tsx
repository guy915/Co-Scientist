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
  askQuestionUrl: vi.fn(),
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
  it('opens on a chat-first screen with the minimal sidebar', () => {
    renderWorkspace();

    expect(
      screen.getByRole('heading', {
        name: 'Drive novel scientific discovery with Co-Scientist.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Base')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Describe a research goal...'),
    ).toBeInTheDocument();
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
    expect(screen.getByText('Hypothesis tournament')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Start'));

    await waitFor(() => {
      expect(apiMock.createRun).toHaveBeenCalledWith(
        expect.objectContaining({
          research_goal: 'Investigate glucose homeostasis under cold stress.',
        }),
      );
      expect(apiMock.startRun).toHaveBeenCalledWith('run-1');
    });

    expect(
      await screen.findByText('Mitochondrial feedback hypothesis'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Report ready').length).toBeGreaterThan(0);
  });

  it('routes active-run questions to streamed Q&A instead of steering', async () => {
    apiMock.getRun.mockResolvedValue(minimalRun({status: 'running'}));
    streamMock.useRunStream.mockReturnValue({
      events: [],
      lastSeq: 0,
      isOpen: true,
      error: null,
      terminal: false,
    });
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder();
        controller.enqueue(
          enc.encode('data: {"type":"chunk","content":"Reviewing evidence"}\n'),
        );
        controller.close();
      },
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(body, {status: 200}));
    vi.stubGlobal('fetch', fetchMock);

    renderWorkspace();

    const input = screen.getByPlaceholderText('Describe a research goal...');
    fireEvent.change(input, {target: {value: 'Investigate glucose control.'}});
    fireEvent.submit(input.closest('form')!);
    fireEvent.click(await screen.findByText('Start'));

    const composer = await screen.findByPlaceholderText(
      'Ask a question or steer the active run...',
    );
    fireEvent.change(composer, {target: {value: 'What is it doing?'}});
    fireEvent.submit(composer.closest('form')!);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/runs/run-1/messages/ask',
        expect.objectContaining({method: 'POST'}),
      );
    });
    expect(apiMock.sendMessage).not.toHaveBeenCalledWith(
      'run-1',
      'What is it doing?',
      'steering',
    );
  });

  it('starts a fresh welcome chat from the top-left home control', async () => {
    renderWorkspace();

    const input = screen.getByPlaceholderText('Describe a research goal...');
    fireEvent.change(input, {target: {value: 'Investigate glucose control.'}});
    fireEvent.submit(input.closest('form')!);
    fireEvent.click(await screen.findByText('Start'));

    expect(await screen.findByLabelText('Run progress')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('New chat'));

    expect(
      screen.getByRole('heading', {
        name: 'Drive novel scientific discovery with Co-Scientist.',
      }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Run progress')).not.toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Describe a research goal...'),
    ).toBeInTheDocument();
  });

  it('routes active-run instructions to steering', async () => {
    apiMock.getRun.mockResolvedValue(minimalRun({status: 'running'}));
    streamMock.useRunStream.mockReturnValue({
      events: [],
      lastSeq: 0,
      isOpen: true,
      error: null,
      terminal: false,
    });

    renderWorkspace();

    const input = screen.getByPlaceholderText('Describe a research goal...');
    fireEvent.change(input, {target: {value: 'Investigate glucose control.'}});
    fireEvent.submit(input.closest('form')!);
    fireEvent.click(await screen.findByText('Start'));

    const composer = await screen.findByPlaceholderText(
      'Ask a question or steer the active run...',
    );
    fireEvent.change(composer, {
      target: {value: 'Focus the next pass on mitochondrial mechanisms.'},
    });
    fireEvent.submit(composer.closest('form')!);

    await waitFor(() => {
      expect(apiMock.sendMessage).toHaveBeenCalledWith(
        'run-1',
        'Focus the next pass on mitochondrial mechanisms.',
        'steering',
      );
    });
    const progress = screen.getByLabelText('Run progress');
    const steeringMessage = await screen.findByText(
      'Focus the next pass on mitochondrial mechanisms.',
    );
    expect(
      progress.compareDocumentPosition(steeringMessage) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const reportReady = screen.getByText(
      'The polished report is available as a separate structured page.',
    );
    expect(
      reportReady.compareDocumentPosition(steeringMessage) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('keeps live progress before later active-run messages', async () => {
    const runCreatedAt = Date.now() / 1000 - 60;
    apiMock.createRun.mockResolvedValue(
      minimalRun({created_at: runCreatedAt, status: 'running'}),
    );
    apiMock.getRun.mockResolvedValue(
      minimalRun({created_at: runCreatedAt, status: 'running'}),
    );
    streamMock.useRunStream.mockReturnValue({
      events: [
        {
          seq: 12,
          type: 'ranking',
          payload: {label: 'Engine Ranking'},
          created_at: Date.now() / 1000 + 60,
        },
      ],
      lastSeq: 12,
      isOpen: true,
      error: null,
      terminal: false,
    });

    renderWorkspace();

    const input = screen.getByPlaceholderText('Describe a research goal...');
    fireEvent.change(input, {target: {value: 'Investigate glucose control.'}});
    fireEvent.submit(input.closest('form')!);
    fireEvent.click(await screen.findByText('Start'));

    const composer = await screen.findByPlaceholderText(
      'Ask a question or steer the active run...',
    );
    fireEvent.change(composer, {target: {value: 'Focus on mitophagy.'}});
    fireEvent.submit(composer.closest('form')!);

    const progress = await screen.findByLabelText('Run progress');
    const steeringMessage = await screen.findByText('Focus on mitophagy.');
    expect(
      progress.compareDocumentPosition(steeringMessage) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('keeps post-report local messages below the report summary', async () => {
    renderWorkspace();

    const input = screen.getByPlaceholderText('Describe a research goal...');
    fireEvent.change(input, {target: {value: 'Investigate glucose control.'}});
    fireEvent.submit(input.closest('form')!);
    fireEvent.click(await screen.findByText('Start'));

    const composer = await screen.findByPlaceholderText(
      'Ask what this run is doing...',
    );
    fireEvent.change(composer, {target: {value: 'Thanks for the summary.'}});
    fireEvent.submit(composer.closest('form')!);

    const reportReady = await screen.findByText(
      'The polished report is available as a separate structured page.',
    );
    const laterMessage = await screen.findByText('Thanks for the summary.');
    expect(
      reportReady.compareDocumentPosition(laterMessage) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
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
    expect(
      screen.getByText('Stronger mechanistic specificity.'),
    ).toBeInTheDocument();
  });
});

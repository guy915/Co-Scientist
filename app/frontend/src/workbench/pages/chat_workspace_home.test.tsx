import {fireEvent, screen, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi, describe} from 'vitest';
import {
  installChatWorkspaceMocks,
  renderWorkspace,
  apiMock,
  minimalRun,
} from './chat_workspace_test_helpers';
import type {Interview} from '@/api/runs';
import {SUGGESTIONS} from './chat_home_stage';

describe('chat workspace home', () => {
  beforeEach(() => {
    installChatWorkspaceMocks();
  });

  it('opens on the reference-style Co-Scientist home screen', async () => {
    renderWorkspace();

    expect(
      screen.getByRole('heading', {
        name: 'What breakthrough should we make today?',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('Recents')).toBeInTheDocument();
    expect(screen.getByText('Frame the research goal')).toBeInTheDocument();
    expect(screen.getByText('Generate hypotheses')).toBeInTheDocument();
    expect(
      screen.getByText('Pressure-test the best ideas'),
    ).toBeInTheDocument();
    expect(screen.queryByText('AI Co-Scientist')).toBeNull();
    expect(
      screen.getByText('Start a new research goal to begin'),
    ).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(
      await screen.findByText(/ferroptosis in pancreatic cancer cells/i, {
        selector: '.reference-recent-description',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {
        name: /ferroptosis in pancreatic cancer cells/i,
      }),
    ).toHaveAttribute('href', '/runs/demo-ferroptosis/details');
  });

  it('points from the composer down to the landing page', async () => {
    renderWorkspace();
    const hint = screen.getByRole('button', {
      name: 'Scroll to see how Co-Scientist works',
    });
    expect(
      await screen.findByRole('navigation', {name: 'Landing sections'}),
    ).toBeInTheDocument();
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    fireEvent.click(hint);
    expect(scrollIntoView.mock.contexts[0]).toBe(
      document.getElementById('landing'),
    );
  });
});

describe('chat workspace home active empty', () => {
  beforeEach(() => {
    installChatWorkspaceMocks();
  });

  it('shows active recents with the run step flow', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-active',
        research_goal: 'Investigate synaptic pruning therapies.',
        status: 'running',
        completed_at: null,
        latest_stage: null,
        execution_progress: {
          determinate: false,
          completed_tasks: 3,
          total_tasks: 5,
          fraction: null,
          active_task: 'engine.fanout.reflection.item',
          queued_tasks: 1,
        },
        summary: {
          events: 9,
          hypotheses: 3,
          evidence: 0,
          matches: 1,
          reviews: 2,
        },
        updated_at: 20,
      }),
    ]);

    renderWorkspace();

    expect(await screen.findByText('In Progress')).toBeInTheDocument();
    expect(screen.getByText('Exploring focus areas')).toBeInTheDocument();
    expect(screen.getByText('Generating hypotheses')).toBeInTheDocument();
    expect(screen.getByText('Reviewing hypotheses')).toBeInTheDocument();
    expect(screen.queryByText('Playing tournament')).toBeNull();
  });

  it('shows the reference empty recents placeholder', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([]);

    const {container} = renderWorkspace();

    expect(
      await screen.findByText('You have not started any sessions yet.'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('.reference-recents-empty-icon'),
    ).not.toBeNull();
    expect(container.querySelector('.reference-assistant-dot')).toBeNull();
  });
});

describe('chat workspace home completed cards', () => {
  beforeEach(() => {
    installChatWorkspaceMocks();
  });

  it('uses the run-list top_elo for completed home-card top scores', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-scored',
        research_goal: 'Rank host-pathogen target hypotheses.',
        top_elo: 1324,
      }),
    ]);

    renderWorkspace();

    expect(await screen.findByText('Top score: 1324')).toBeInTheDocument();
    expect(screen.queryByText('Top score: 1240')).toBeNull();
  });

  it('renders the run’s real top hypotheses on a completed card', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-real-titles',
        research_goal: 'Rank host-pathogen target hypotheses.',
        top_hypotheses: [
          'Metabolic refuge disruption hypothesis',
          'Biofilm redox-state vulnerability hypothesis',
        ],
      }),
    ]);

    renderWorkspace();

    expect(
      await screen.findByText('Metabolic refuge disruption hypothesis'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Biofilm redox-state vulnerability hypothesis'),
    ).toBeInTheDocument();
  });

  it('omits the winner list for a run that produced no hypotheses', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-no-hyps',
        research_goal: 'A run that failed before generating anything.',
        status: 'failed',
        top_hypotheses: [],
      }),
    ]);

    const {container} = renderWorkspace();

    await screen.findAllByText(/failed before generating anything/i);
    expect(container.querySelector('.reference-winner-list')).toBeNull();
  });

  it('omits the winning-ideas chips on a cancelled run', async () => {
    // Cancelled tournaments have no winners or earned top score.
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-cancelled',
        research_goal: 'A run the scientist stopped part way.',
        status: 'cancelled',
        top_hypotheses: ['A half-ranked idea'],
      }),
    ]);

    renderWorkspace();

    await screen.findAllByText(/stopped part way/i);
    expect(screen.queryByText('Winning ideas')).toBeNull();
    expect(screen.queryByText(/^Top score:/)).toBeNull();
    expect(screen.queryByText('A half-ranked idea')).toBeNull();
  });

  it('keeps the winning-ideas chips on a completed run', async () => {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.listRuns.mockResolvedValue([
      minimalRun({
        id: 'run-done',
        research_goal: 'A run that finished its tournament.',
        top_hypotheses: ['A ranked idea'],
      }),
    ]);

    renderWorkspace();

    expect(await screen.findByText('Winning ideas')).toBeInTheDocument();
  });

  it.each([undefined, null])(
    'omits an unknown completed-run top score (%s)',
    async top_elo => {
      apiMock.listDemoRuns.mockResolvedValue([]);
      apiMock.listRuns.mockResolvedValue([minimalRun({top_elo})]);
      renderWorkspace();

      expect(await screen.findByText('Winning ideas')).toBeInTheDocument();
      expect(screen.queryByText(/^Top score:/)).toBeNull();
    },
  );
});

describe('chat workspace home recents window', () => {
  beforeEach(() => {
    installChatWorkspaceMocks();
  });

  function seedSixRecentRuns() {
    apiMock.listDemoRuns.mockResolvedValue([]);
    apiMock.getHypotheses.mockResolvedValue([]);
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
  }

  it('shows four recent cards before revealing the rest', async () => {
    seedSixRecentRuns();

    renderWorkspace();

    expect(
      await screen.findAllByText('Recent research question 6'),
    ).not.toHaveLength(0);
    await waitFor(() => {
      expect(screen.getAllByText('Top score: 1200')).not.toHaveLength(0);
    });
    expect(screen.getAllByText('Recent research question 3')).not.toHaveLength(
      0,
    );
    expect(screen.queryByText('Recent research question 2')).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Show more'}));

    expect(screen.getAllByText('Recent research question 2')).not.toHaveLength(
      0,
    );
    expect(screen.getAllByText('Recent research question 1')).not.toHaveLength(
      0,
    );
    expect(screen.queryByRole('button', {name: 'Show more'})).toBeNull();

    fireEvent.click(screen.getByRole('button', {name: 'Show less'}));

    expect(screen.queryByText('Recent research question 2')).toBeNull();
    expect(screen.getByRole('button', {name: 'Show more'})).toBeInTheDocument();
  });
});

describe('chat workspace chats', () => {
  beforeEach(() => {
    installChatWorkspaceMocks();
  });

  function activeInterview(): Interview {
    return {
      id: 'interview-7',
      client_id: 'client-1',
      status: 'active',
      documents: [],
      fields: {
        research_challenge: 'Study liver fibrosis',
        focus_area: [],
        preferences: [],
        title: null,
      },
      current_question: 'Which mechanisms should I prioritize?',
      turns: [
        {
          id: 1,
          role: 'user',
          content: 'Study liver fibrosis',
          reasoning: null,
          fallback: false,
          questions: [],
          created_at: 1,
        },
        {
          id: 2,
          role: 'agent',
          content: 'Which mechanisms should I prioritize?',
          reasoning: 'No mechanism named yet, so ask for one.',
          fallback: false,
          questions: [],
          created_at: 2,
        },
      ],
      created_at: 1,
      updated_at: 2,
      completed_at: null,
    };
  }

  it('lists a chat and routes to it as soon as the first turn lands', async () => {
    renderWorkspace();

    const input = screen.getByRole('textbox');
    fireEvent.change(input, {target: {value: 'Study liver fibrosis'}});
    fireEvent.submit(input.closest('form')!);

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/chats/interview-1',
      );
    });
    expect(apiMock.listInterviews).toHaveBeenCalled();
  });

  it('reopens a chat from its id with the transcript and its thinking', async () => {
    const interview = activeInterview();
    apiMock.getInterview.mockResolvedValue(interview);

    renderWorkspace('/chats/interview-7');

    expect(await screen.findByText('Study liver fibrosis')).toBeInTheDocument();
    expect(
      screen.getByText('Which mechanisms should I prioritize?'),
    ).toBeInTheDocument();
    expect(screen.getByText('Thinking')).toBeInTheDocument();
    expect(
      screen.getByText('No mechanism named yet, so ask for one.'),
    ).toBeInTheDocument();
    expect(apiMock.getInterview).toHaveBeenCalledWith('interview-7');
  });
});

describe('chat home stage', () => {
  describe('SUGGESTIONS', () => {
    it('offers the default set of home suggestions', () => {
      expect(SUGGESTIONS[0].preview).toMatch(/glioblastoma/i);
    });
  });
});

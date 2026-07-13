import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import type {Hypothesis, MatchRow, Report, RunWithSummary} from '@/api/runs';
import {makeHypothesis} from '@/test-fixtures';
import {ResearchOverviewView} from './run_detail_overview';

function makeRun(overrides: Partial<RunWithSummary> = {}): RunWithSummary {
  return {
    id: 'run-1',
    research_goal: 'Study pathway X',
    status: 'completed',
    config: {},
    created_at: 1_700_000_000,
    completed_at: 1_700_000_000 + 3 * 3600,
    ...overrides,
  } as unknown as RunWithSummary;
}

function makeMatch(id: number, overrides: Partial<MatchRow> = {}): MatchRow {
  return {id, ...overrides} as unknown as MatchRow;
}

function makeReport(overrides: Partial<Report['payload']> = {}): Report {
  return {
    id: 'rep-1',
    run_id: 'run-1',
    markdown_path: '',
    created_at: 1,
    payload: {
      research_goal: 'Study pathway X',
      provider: 'mock',
      leaderboard: [],
      ...overrides,
    },
  } as unknown as Report;
}

describe('ResearchOverviewView', () => {
  it('falls back to live hypotheses/matches when there is no persisted report yet', async () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({id: 'h1', title: 'Top idea', elo_rating: 1700}),
    ];
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={null}
        hypotheses={hypotheses}
        matches={[makeMatch(1)]}
      />,
    );

    expect(
      screen.getByText(
        'The research overview appears after Co-Scientist finishes the final synthesis step.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Top idea')).toBeInTheDocument();
    expect(
      screen.getByText('1 tournament matches have been recorded for this run.'),
    ).toBeInTheDocument();
  });

  it('shows the pre-synthesis placeholders for research directions/specific aims/tournament with no data', () => {
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={null}
        hypotheses={[]}
        matches={[]}
      />,
    );
    expect(
      screen.getByText('Tournament matches appear here once ranking begins.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Research directions')).not.toBeInTheDocument();
    expect(screen.queryByText('Specific aims')).not.toBeInTheDocument();
    expect(screen.queryByText('Winning ideas')).not.toBeInTheDocument();
  });

  it('renders the full synthesized report: summary, research directions, specific aims, and leaderboard', () => {
    const report = makeReport({
      hypothesis_count: 2,
      evidence_count: 11,
      match_count: 3,
      idea_buckets: {
        high_potential: [
          {id: 'h1', title: 'Leaderboard idea', reason: 'Released.'},
        ],
        non_viable: [
          {id: 'h3', title: 'Rejected idea', reason: 'Contradicted.'},
        ],
      },
      leaderboard: [
        {id: 'h1', title: 'Leaderboard idea', elo: 1735},
        {id: 'h2', title: 'Second idea', elo: 1600},
      ],
      research_overview: {
        overview: {
          summary: 'A synthesized summary of the research.',
          research_directions: [
            {
              title: 'Direction one',
              importance: 'It matters because X.',
              suggested_experiments: ['Experiment A', 'Experiment B'],
            },
            {
              title: 'Direction two (no experiments)',
              importance: 'It matters because Y.',
              suggested_experiments: [],
            },
          ],
        },
        nih_specific_aims: {
          introduction: 'An introduction to the aims.',
          aims: [
            {
              aim: 'Aim 1: Do the thing',
              rationale: 'Because reasons.',
              approach: 'Via this approach.',
            },
          ],
          impact: 'The impact statement.',
        },
        research_contacts: [
          {
            candidate_id: 'author-1-1',
            name: 'Ada Researcher',
            expertise: 'Fibrosis mechanisms',
            justification: 'Authored a directly relevant analyzed paper.',
            source_id: 'PMID:123',
            source_title: 'A fibrosis study',
            source_url: 'https://pubmed.ncbi.nlm.nih.gov/123/',
            source: 'pubmed',
          },
        ],
      },
    });

    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );

    expect(
      screen.getByText('A synthesized summary of the research.'),
    ).toBeInTheDocument();
    expect(screen.getByText('High Potential')).toBeInTheDocument();
    expect(screen.getByText('Non-Viable')).toBeInTheDocument();
    expect(screen.getByText('Verified ideas')).toBeInTheDocument();
    expect(screen.getByText('Sources Analyzed')).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();

    expect(
      screen.getByRole('heading', {name: 'Research directions'}),
    ).toBeInTheDocument();
    expect(screen.getByText('Direction one')).toBeInTheDocument();
    expect(screen.getByText('It matters because X.')).toBeInTheDocument();
    expect(screen.getByText('Experiment A')).toBeInTheDocument();
    expect(screen.getByText('Experiment B')).toBeInTheDocument();
    // Second direction has no suggested experiments, so no list under it.
    expect(
      screen.getByText('Direction two (no experiments)'),
    ).toBeInTheDocument();

    expect(
      screen.getByRole('heading', {name: 'Specific aims'}),
    ).toBeInTheDocument();
    expect(
      screen.getByText('An introduction to the aims.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Aim 1: Do the thing')).toBeInTheDocument();
    expect(screen.getByText('Because reasons.')).toBeInTheDocument();
    expect(screen.getByText('Via this approach.')).toBeInTheDocument();
    expect(screen.getByText('The impact statement.')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {name: 'Research contacts'}),
    ).toBeInTheDocument();
    expect(screen.getByText('Ada Researcher')).toBeInTheDocument();
    expect(
      screen.getByRole('link', {name: 'Evidence: A fibrosis study'}),
    ).toHaveAttribute('href', 'https://pubmed.ncbi.nlm.nih.gov/123/');

    expect(
      screen.getByRole('heading', {name: 'Winning ideas'}),
    ).toBeInTheDocument();
    expect(screen.getByText('Leaderboard idea')).toBeInTheDocument();
    expect(screen.getByText('Elo rating: 1735')).toBeInTheDocument();

    expect(
      screen.getByText(
        /A total of 2 ideas were explored over 3 hours with the highest Elo rating of 1735 points and a total of 3 matches were played\./,
      ),
    ).toBeInTheDocument();
  });

  it('omits the introduction/impact paragraphs when a specific aim lacks them', () => {
    const report = makeReport({
      research_overview: {
        nih_specific_aims: {
          aims: [
            {
              aim: 'Aim without surrounding copy',
              rationale: 'R',
              approach: 'A',
            },
          ],
        },
      },
    });
    render(
      <ResearchOverviewView
        run={makeRun()}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
    expect(
      screen.getByText('Aim without surrounding copy'),
    ).toBeInTheDocument();
  });

  it('omits the duration clause when the run has a zero or negative completed/created delta', () => {
    const report = makeReport({
      hypothesis_count: 1,
      leaderboard: [{id: 'h1', title: 'Only idea', elo: 1500}],
    });
    render(
      <ResearchOverviewView
        run={makeRun({created_at: 1000, completed_at: 1000})}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
    const stat = screen.getByText(/A total of 1 idea was explored/);
    expect(stat.textContent).not.toContain('over');
  });

  it('omits the duration and Elo clauses when the run and leaderboard/hypotheses carry no data', () => {
    const report = makeReport({hypothesis_count: 1, leaderboard: []});
    render(
      <ResearchOverviewView
        run={null}
        report={report}
        hypotheses={[]}
        matches={[]}
      />,
    );
    const stat = screen.getByText(/A total of 1 idea was explored/);
    expect(stat.textContent).toBe('A total of 1 idea was explored.');
  });
});

import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {ResearchOverviewView} from './run_detail_overview';
import {makeReport, makeRun} from './run_detail_overview_test_support';

it('omits intro/impact paragraphs when a specific aim lacks them', () => {
  const report = makeReport({
    research_overview: {
      nih_specific_aims: {
        aims: [
          {
            overarching_goal: 'Aim without surrounding copy',
            hypothesis: 'R',
            reasoning: 'A',
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
  expect(screen.getByText('Aim without surrounding copy')).toBeInTheDocument();
});

it('omits the duration clause on a zero or negative delta', () => {
  const report = makeReport({
    idea_count: 1,
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

it('omits the duration and Elo clauses when no data is present', () => {
  const report = makeReport({idea_count: 1, leaderboard: []});
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

it('counts every idea explored, not just the released ones', () => {
  // A run that explores 22 ideas and releases 2 announced "A total of 2
  // ideas were explored" directly above its own list of 22, because the
  // lead stat read the post-gate count.
  const report = makeReport({
    idea_count: 22,
    hypothesis_count: 2,
    leaderboard: [],
  });
  render(
    <ResearchOverviewView
      run={null}
      report={report}
      hypotheses={[]}
      matches={[]}
    />,
  );
  expect(
    screen.getByText('A total of 22 ideas were explored.'),
  ).toBeInTheDocument();
});

it('reports verified ideas separately from high-potential ones', () => {
  // The tile repeated the High Potential count, so a run could claim two
  // verified ideas while every idea in the list carried an "Unverified"
  // badge. It is now the server's count of ideas with a supported claim.
  const report = makeReport({
    verified_count: 0,
    idea_buckets: {
      high_potential: [
        {id: 'h1', title: 'Released one', reason: 'Released.'},
        {id: 'h2', title: 'Released two', reason: 'Released.'},
      ],
      non_viable: [],
    },
  });
  render(
    <ResearchOverviewView
      run={null}
      report={report}
      hypotheses={[]}
      matches={[]}
    />,
  );
  const tile = screen.getByText('Verified ideas').closest('div');
  expect(tile?.textContent).toBe('Verified ideas0');
  expect(screen.getByText('High Potential').closest('div')?.textContent).toBe(
    'High Potential2',
  );
});

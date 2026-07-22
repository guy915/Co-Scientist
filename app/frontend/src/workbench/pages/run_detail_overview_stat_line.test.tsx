import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {ResearchOverviewView} from './run_detail_overview';
import {makeReport, makeRun} from './run_detail_overview_test_support';

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
  expect(screen.getByText('Aim without surrounding copy')).toBeInTheDocument();
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

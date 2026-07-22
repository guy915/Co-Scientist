import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import type {Hypothesis} from '@/api/runs';
import {makeHypothesis, makeMatch} from '@/test_fixtures';
import {ResearchOverviewView} from './run_detail_overview';
import {makeRun} from './run_detail_overview_test_support';

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

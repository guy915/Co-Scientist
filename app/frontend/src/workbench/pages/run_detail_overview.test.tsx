import {screen} from '@testing-library/react';
import {expect, it, describe} from 'vitest';
import type {Hypothesis} from '@/api/runs';
import {makeHypothesis, makeMatch} from '@/test_fixtures';
import {renderOverview} from './run_detail_overview_test_support';

describe('run detail overview', () => {
  it('falls back to live data when there is no persisted report', async () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({id: 'h1', title: 'Top idea', elo_rating: 1700}),
    ];
    renderOverview({hypotheses, matches: [makeMatch(1)]});

    expect(
      screen.getByText(
        'The research overview appears after Co-Scientist finishes the final ' +
          'synthesis step.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Top idea')).toBeInTheDocument();
    expect(
      screen.getByText('1 tournament matches have been recorded for this run.'),
    ).toBeInTheDocument();
  });
});

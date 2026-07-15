import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {IdeasTab} from './ideas_tab';
import type {Hypothesis, Review} from '@/api/runs';
import {makeHypothesis} from '@/test-fixtures';

describe('IdeasTab', () => {
  it('shows the empty state when there are no hypotheses', () => {
    render(<IdeasTab hypotheses={[]} reviews={[]} />);
    expect(
      screen.getByText('Hypotheses appear here once the generation node runs.'),
    ).toBeInTheDocument();
  });

  it('renders idea rows sorted by Elo with their scores', () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({
        id: 'low',
        title: 'Low-ranked idea',
        statement: 'A weaker statement.',
        elo_rating: 1150,
      }),
      makeHypothesis({
        id: 'high',
        title: 'High-ranked idea',
        statement: 'A stronger statement.',
        elo_rating: 1300,
        win_count: 4,
        loss_count: 1,
      }),
    ];
    render(<IdeasTab hypotheses={hypotheses} reviews={[]} />);
    expect(screen.getAllByText('High-ranked idea')[0]).toBeInTheDocument();
    expect(screen.getByText('Low-ranked idea')).toBeInTheDocument();
    // Default sort is by Elo descending; the higher Elo badge is rendered.
    expect(screen.getByText('Elo rating: 1300')).toBeInTheDocument();
    expect(screen.queryByText('80% wins')).not.toBeInTheDocument();

    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('High-ranked idea');
    expect(rows[1]).toHaveTextContent('Low-ranked idea');
  });

  it('flags an evidence-less idea with the "Unverified" chip', () => {
    const {container} = render(
      <IdeasTab
        hypotheses={[
          makeHypothesis({
            id: 'grounded',
            title: 'Grounded idea',
            elo_rating: 1300,
            unverified: false,
          }),
          makeHypothesis({
            id: 'latent',
            title: 'Latent idea',
            elo_rating: 1250,
            unverified: true,
          }),
        ]}
        reviews={[]}
      />,
    );
    // Rank-and-publish: both ideas are published and ranked, and only the
    // evidence-less one carries the "Unverified" chip.
    expect(screen.getAllByText('Grounded idea').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Latent idea').length).toBeGreaterThan(0);
    const chips = container.querySelectorAll('.idea-unverified-chip');
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent('Unverified');
  });

  it('renders reference detail sections without the legacy detail link', () => {
    const reviews: Review[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        reviewer_agent: 'reflection',
        summary: 'Reasonable.',
        critique: 'Needs a control arm.',
        novelty: 7,
        plausibility: 8,
        testability: 6,
        overall: 7,
      },
    ];
    render(
      <IdeasTab
        hypotheses={[makeHypothesis({id: 'h1', title: 'Focusable idea'})]}
        reviews={reviews}
      />,
    );
    expect(screen.getByText('Review summary')).toBeInTheDocument();
    expect(screen.getByText('Full review')).toBeInTheDocument();
    expect(screen.getByText('Reasonable.')).toBeInTheDocument();
    expect(screen.getByText('Needs a control arm.')).toBeInTheDocument();
    expect(screen.queryByText('Full legacy detail')).not.toBeInTheDocument();
  });
});

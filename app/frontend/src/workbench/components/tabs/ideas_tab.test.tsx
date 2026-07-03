import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {IdeasTab} from './ideas_tab';
import type {CitationRow, Hypothesis, Review} from '@/api/runs';

function makeHypothesis(over: Partial<Hypothesis> = {}): Hypothesis {
  return {
    id: 'h1',
    run_id: 'r1',
    parent_id: null,
    generation: 0,
    title: 'Untitled hypothesis',
    statement: 'A statement.',
    mechanism: null,
    expected_effect: null,
    experimental_context: null,
    created_by_agent: 'generate',
    created_at: 0,
    elo_rating: 1200,
    win_count: 0,
    loss_count: 0,
    novelty_score: null,
    plausibility_score: null,
    testability_score: null,
    safety_status: null,
    status: null,
    cluster_id: null,
    ...over,
  };
}

describe('IdeasTab', () => {
  it('shows the empty state when there are no hypotheses', () => {
    render(<IdeasTab hypotheses={[]} citations={[]} reviews={[]} />);
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
    render(<IdeasTab hypotheses={hypotheses} citations={[]} reviews={[]} />);
    expect(screen.getAllByText('High-ranked idea')[0]).toBeInTheDocument();
    expect(screen.getByText('Low-ranked idea')).toBeInTheDocument();
    // Default sort is by Elo descending; the higher Elo badge is rendered.
    expect(screen.getByText('Elo rating: 1300')).toBeInTheDocument();
    expect(screen.queryByText('80% wins')).not.toBeInTheDocument();

    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('High-ranked idea');
    expect(rows[1]).toHaveTextContent('Low-ranked idea');
  });

  it('keeps citation counters out of the reference row layout', () => {
    const hypotheses = [makeHypothesis({id: 'h1', title: 'Cited idea'})];
    const citations: CitationRow[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        evidence_id: 'e1',
        claim: 'Claim one.',
        state: 'verified',
      },
      {
        id: 2,
        hypothesis_id: 'h1',
        evidence_id: 'e2',
        claim: 'Claim two.',
        state: 'partial',
      },
    ];
    render(
      <IdeasTab hypotheses={hypotheses} citations={citations} reviews={[]} />,
    );
    expect(screen.getAllByText('Cited idea').length).toBeGreaterThan(0);
    expect(screen.queryByText('1/2 verified')).not.toBeInTheDocument();
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
        citations={[]}
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

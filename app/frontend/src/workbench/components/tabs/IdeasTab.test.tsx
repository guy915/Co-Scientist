import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {IdeasTab} from './IdeasTab';
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
    render(
      <IdeasTab
        hypotheses={[]}
        citations={[]}
        reviews={[]}
        onFocus={() => {}}
      />,
    );
    expect(
      screen.getByText('Hypotheses appear here once the generation node runs.'),
    ).toBeInTheDocument();
  });

  it('renders hypothesis rows sorted by Elo with their scores', () => {
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
    render(
      <IdeasTab
        hypotheses={hypotheses}
        citations={[]}
        reviews={[]}
        onFocus={() => {}}
      />,
    );
    expect(screen.getByText('High-ranked idea')).toBeInTheDocument();
    expect(screen.getByText('Low-ranked idea')).toBeInTheDocument();
    // Default sort is by Elo descending; the higher Elo badge is rendered.
    expect(screen.getByText('Elo 1300')).toBeInTheDocument();
    // Win rate badge: 4 / (4+1) = 80%.
    expect(screen.getByText('80%')).toBeInTheDocument();

    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('High-ranked idea');
    expect(rows[1]).toHaveTextContent('Low-ranked idea');
  });

  it('surfaces verified-citation counts on a row', () => {
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
      <IdeasTab
        hypotheses={hypotheses}
        citations={citations}
        reviews={[]}
        onFocus={() => {}}
      />,
    );
    // One of two citations is verified.
    expect(screen.getByText('1/2 Verified')).toBeInTheDocument();
  });

  it('invokes onFocus with the hypothesis id from the detail link', async () => {
    const onFocus = vi.fn();
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
        onFocus={onFocus}
      />,
    );
    const user = userEvent.setup();
    // Expand the row to reveal the "Open detail" action.
    await user.click(screen.getByText('Focusable idea'));
    await user.click(screen.getByText('Open detail'));
    expect(onFocus).toHaveBeenCalledWith('h1');
  });
});

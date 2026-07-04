import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {IdeasTab} from './ideas_tab';
import type {CitationRow, Hypothesis, Report, Review} from '@/api/runs';

function makeHypothesis(over: Partial<Hypothesis> = {}): Hypothesis {
  return {
    id: 'h1',
    run_id: 'r1',
    parent_id: null,
    generation: 0,
    category: null,
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

  it('derives the Agent Insights band from run artifacts', () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({id: 'high', elo_rating: 1320}),
      makeHypothesis({id: 'mid', elo_rating: 1200}),
      makeHypothesis({id: 'low', elo_rating: 1080}),
    ];
    const citations: CitationRow[] = [
      {
        id: 1,
        hypothesis_id: 'high',
        evidence_id: 'e1',
        claim: 'Claim.',
        state: 'verified',
      },
      {
        id: 2,
        hypothesis_id: 'high',
        evidence_id: 'e2',
        claim: 'Claim.',
        state: 'verified',
      },
      {
        id: 3,
        hypothesis_id: 'mid',
        evidence_id: 'e1',
        claim: 'Claim.',
        state: 'partial',
      },
    ];
    render(
      <IdeasTab hypotheses={hypotheses} citations={citations} reviews={[]} />,
    );
    const band = screen.getByLabelText('Agent insights').parentElement!;
    // Buckets are extremes, not a partition: high potential (strictly above the
    // 1200 baseline) = high = 1; non-viable (strictly below) = low = 1. The mid
    // idea at exactly the baseline counts in neither bucket.
    expect(band).toHaveTextContent('High potential ideas');
    expect(band).toHaveTextContent('Non-viable ideas');
    // Verified ideas = distinct hypotheses with a verified citation = 1 (high).
    expect(band).toHaveTextContent('Number of verified ideas');
    // Sources analyzed = distinct evidence ids (e1, e2) = 2.
    expect(band).toHaveTextContent('Sources analyzed');
    const values = band.querySelectorAll('.idea-stat-value');
    expect([...values].map(v => v.textContent)).toEqual(['1', '1', '1', '2']);
  });

  it('buckets mixed elos above, below, and at the baseline as extremes', () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({id: 'above1', elo_rating: 1290}),
      makeHypothesis({id: 'above2', elo_rating: 1201}),
      makeHypothesis({id: 'at', elo_rating: 1200}),
      makeHypothesis({id: 'below', elo_rating: 1199}),
    ];
    render(<IdeasTab hypotheses={hypotheses} citations={[]} reviews={[]} />);
    const band = screen.getByLabelText('Agent insights').parentElement!;
    const values = band.querySelectorAll('.idea-stat-value');
    // High potential = 2 (1290, 1201); non-viable = 1 (1199); the at-baseline
    // idea (1200) counts in neither, so the two buckets do not sum to 4.
    expect([...values].map(v => v.textContent)).toEqual(['2', '1', '0', '0']);
  });

  it('counts zero in both buckets when every idea sits at the baseline', () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({id: 'a', elo_rating: 1200}),
      makeHypothesis({id: 'b', elo_rating: 1200}),
      makeHypothesis({id: 'c', elo_rating: 1200}),
    ];
    render(<IdeasTab hypotheses={hypotheses} citations={[]} reviews={[]} />);
    const band = screen.getByLabelText('Agent insights').parentElement!;
    const values = band.querySelectorAll('.idea-stat-value');
    // A fresh run (all at baseline) is neither high potential nor non-viable.
    expect([...values].map(v => v.textContent)).toEqual(['0', '0', '0', '0']);
  });

  it('prefers the report research-overview summary for the insight body', () => {
    const report = {
      id: 'rep1',
      run_id: 'r1',
      payload: {
        research_goal: 'Goal',
        provider: 'mock',
        leaderboard: [],
        research_overview: {
          overview: {summary: 'A synthesized overview summary.'},
        },
      },
      markdown_path: '',
      created_at: 0,
    } as Report;
    render(
      <IdeasTab
        hypotheses={[makeHypothesis({id: 'h1'})]}
        citations={[]}
        reviews={[]}
        report={report}
      />,
    );
    expect(
      screen.getByText('A synthesized overview summary.'),
    ).toBeInTheDocument();
  });
});

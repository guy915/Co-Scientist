import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {TournamentTab} from './tournament_tab';
import type {Hypothesis, MatchRow} from '@/api/runs';

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

describe('TournamentTab', () => {
  it('shows the empty state when no matches have been played', () => {
    render(<TournamentTab matches={[]} hypotheses={[]} />);
    expect(
      screen.getByText(
        'Tournament matchups appear here after the ranking node runs.',
      ),
    ).toBeInTheDocument();
  });

  it('renders the leaderboard and a matchup row from the data', () => {
    const hypotheses: Hypothesis[] = [
      makeHypothesis({
        id: 'winner',
        title: 'mTOR inhibition slows senescence',
        elo_rating: 1240,
        win_count: 3,
        loss_count: 1,
      }),
      makeHypothesis({
        id: 'loser',
        title: 'Autophagy boost extends lifespan',
        elo_rating: 1180,
        win_count: 1,
        loss_count: 3,
      }),
    ];
    const matches: MatchRow[] = [
      {
        id: 1,
        iteration: 2,
        winner_id: 'winner',
        loser_id: 'loser',
        winner_elo_before: 1200,
        winner_elo_after: 1240,
        loser_elo_before: 1200,
        loser_elo_after: 1180,
        rationale: 'Stronger mechanistic grounding.',
        created_at: 0,
      },
    ];
    render(<TournamentTab matches={matches} hypotheses={hypotheses} />);

    expect(screen.getByText('Leaderboard')).toBeInTheDocument();
    // The match-count header reflects the single match.
    expect(screen.getByText('(1)')).toBeInTheDocument();
    // Titles appear in the leaderboard and in both responsive match layouts.
    expect(
      screen.getAllByText('mTOR inhibition slows senescence').length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getAllByText('Autophagy boost extends lifespan').length,
    ).toBeGreaterThanOrEqual(2);
    // The match rationale renders once.
    expect(
      screen.getByText('Stronger mechanistic grounding.'),
    ).toBeInTheDocument();
    // The iteration badge is shown for each responsive layout.
    expect(screen.getAllByText('Iter 2').length).toBeGreaterThanOrEqual(1);
  });
});

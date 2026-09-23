import {fireEvent, render, screen} from '@testing-library/react';
import {expect, it, vi} from 'vitest';
import type {MatchRow} from '@/api/runs';
import {makeHypothesis} from '@/test_fixtures';
import {HypothesisDetail} from './ideas_detail_pane';

vi.mock('@/lib/smooth_scroll', () => ({
  smoothScrollToSection: vi.fn(),
}));

it('shows complete selected-idea match history and expandable stored debates', () => {
  const matches = [
    {
      id: 10,
      iteration: 1,
      winner_id: 'h1',
      loser_id: 'opponent-old',
      winner_elo_before: 1200,
      winner_elo_after: 1218,
      loser_elo_before: 1200,
      loser_elo_after: 1182,
      rationale: 'Historical win rationale.',
      tier: 'clear',
      debate_turns: 1,
      // Same timestamp as the newer row: the greater persisted id breaks ties.
      created_at: 300,
      debate_transcript: null,
    },
    {
      id: 11,
      iteration: 3,
      winner_id: 'opponent-new',
      loser_id: 'h1',
      winner_elo_before: 1300,
      winner_elo_after: 1314,
      loser_elo_before: 1250,
      loser_elo_after: 1236,
      rationale: 'Latest loss rationale.',
      tier: 'decisive',
      debate_turns: 2,
      created_at: 300,
      debate_transcript: JSON.stringify({
        verdict: '2',
        turns: [
          {
            turn: 1,
            favored: '1',
            text: 'The first comparison favors a clear mechanism.',
            first: '1',
          },
          {
            turn: 2,
            favored: '2',
            text: 'The second comparison favors stronger evidence.',
            first: '2',
          },
        ],
      }),
    },
    {
      id: 12,
      iteration: 4,
      winner_id: 'unrelated-a',
      loser_id: 'unrelated-b',
      winner_elo_before: 1300,
      winner_elo_after: 1310,
      loser_elo_before: 1200,
      loser_elo_after: 1190,
      rationale: 'Unrelated rationale.',
      tier: 'narrow',
      debate_turns: 1,
      created_at: 400,
      debate_transcript: null,
    },
  ] satisfies MatchRow[];

  render(
    <HypothesisDetail
      hypothesis={makeHypothesis({id: 'h1'})}
      reviews={[]}
      matches={matches}
    />,
  );

  const latest = screen.getByText('Latest loss rationale.');
  const older = screen.getByText('Historical win rationale.');
  expect(latest.compareDocumentPosition(older)).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
  expect(screen.getByText('Loss against opponent-new')).toBeInTheDocument();
  expect(screen.getByText('Win against opponent-old')).toBeInTheDocument();
  expect(screen.getByText('Iteration 3 · decisive')).toBeInTheDocument();
  const eloLabels = screen.getAllByText('Elo change:');
  expect(eloLabels[0].parentElement).toHaveTextContent('Elo change: -14');
  expect(eloLabels[1].parentElement).toHaveTextContent('Elo change: +18');
  expect(screen.queryByText('Unrelated rationale.')).not.toBeInTheDocument();

  const summary = screen.getByText('Debate transcript (2 turns)');
  const disclosure = summary.closest('details');
  expect(disclosure).not.toBeNull();
  expect(disclosure).not.toHaveAttribute('open');
  fireEvent.click(summary);
  expect(disclosure).toHaveAttribute('open');
  expect(
    screen.getByText('The first comparison favors a clear mechanism.'),
  ).toBeInTheDocument();
  expect(
    screen.getByText('The second comparison favors stronger evidence.'),
  ).toBeInTheDocument();
  expect(screen.getByText('Turn 1:').parentElement).toHaveTextContent(
    'selected hypothesis was presented as Hypothesis 1; this turn favored it.',
  );
  expect(screen.getByText('Turn 2:').parentElement).toHaveTextContent(
    'selected hypothesis was presented as Hypothesis 2; this turn favored the opponent.',
  );
});

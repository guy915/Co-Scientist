import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import type {ClaimEvidenceRow, MatchRow, Review} from '@/api/runs';
import {makeHypothesis} from '@/test-fixtures';
import {HypothesisDetail, SectionsRail} from './ideas_detail_pane';

vi.mock('@/lib/smooth_scroll', () => ({
  smoothScrollToSection: vi.fn(),
}));

describe('HypothesisDetail', () => {
  it('renders the empty-state placeholder when nothing is selected', () => {
    render(<HypothesisDetail hypothesis={null} reviews={[]} matches={[]} />);
    expect(
      screen.getByText(
        'Select a hypothesis to inspect the review and tournament details.',
      ),
    ).toBeInTheDocument();
  });

  it('renders full detail sections, the matching review, and the most recent match', () => {
    const hypothesis = makeHypothesis({
      id: 'h1',
      title: 'A promising idea',
      statement: 'A testable statement.',
      mechanism: 'A described mechanism.',
      expected_effect: 'A measurable effect.',
      win_count: 3,
      loss_count: 1,
      parent_id: 'parent-1',
      generation: 1,
      created_by_agent: 'evolution',
      cluster_id: 'cluster-7',
      safety_status: 'allow',
    });
    const reviews: Review[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        reviewer_agent: 'reflection',
        summary: 'Reasonable and testable.',
        critique: 'Needs a control arm.',
        novelty: 7,
        plausibility: 8,
        testability: 6,
        overall: 7,
      },
      // A review for a different hypothesis must be filtered out.
      {
        id: 2,
        hypothesis_id: 'other',
        reviewer_agent: 'reflection',
        summary: 'Unrelated.',
        critique: 'Unrelated critique.',
        novelty: 1,
        plausibility: 1,
        testability: 1,
        overall: 1,
      },
    ];
    const matches: MatchRow[] = [
      {
        id: 1,
        winner_id: 'h1',
        loser_id: 'h2',
        created_at: 100,
        tier: 'strong',
        rationale: 'An earlier match rationale.',
      } as unknown as MatchRow,
      {
        id: 2,
        winner_id: 'h3',
        loser_id: 'h1',
        created_at: 200,
        tier: 'close',
        debate_turns: 3,
        rationale: 'The latest match rationale.',
      } as unknown as MatchRow,
      // A match not involving this hypothesis must be filtered out.
      {
        id: 3,
        winner_id: 'other-a',
        loser_id: 'other-b',
        created_at: 300,
        tier: 'strong',
        rationale: 'Unrelated match.',
      } as unknown as MatchRow,
    ];

    const claimEvidence: ClaimEvidenceRow[] = [
      {
        id: 1,
        hypothesis_id: 'h1',
        claim: 'A supported claim.',
        label: 'supports',
        supporting: ['A supporting passage.'],
        contradicting: [],
        assessor: 'deterministic-v1',
      },
      {
        id: 2,
        hypothesis_id: 'h1',
        claim: 'An unsupported claim.',
        label: 'insufficient',
        supporting: [],
        contradicting: [],
        assessor: 'deterministic-v1',
      },
      // A claim for a different hypothesis must be filtered out.
      {
        id: 3,
        hypothesis_id: 'other',
        claim: 'Unrelated claim.',
        label: 'contradicts',
        supporting: [],
        contradicting: ['A contradicting passage.'],
        assessor: 'deterministic-v1',
      },
    ];

    render(
      <HypothesisDetail
        hypothesis={hypothesis}
        reviews={reviews}
        matches={matches}
        claimEvidence={claimEvidence}
      />,
    );

    expect(screen.getByText('A testable statement.')).toBeInTheDocument();
    expect(screen.getByText('A promising idea')).toBeInTheDocument();
    expect(
      screen.getByText(/Proposed mechanism of action:/),
    ).toBeInTheDocument();
    expect(screen.getByText('A described mechanism.')).toBeInTheDocument();
    expect(screen.getByText(/Expected effect:/)).toBeInTheDocument();
    expect(screen.getByText('A measurable effect.')).toBeInTheDocument();

    // Provenance & lineage section surfaces origin, generation, cluster, safety.
    expect(
      screen.getByText(/Evolution agent \(refined from a parent\)/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Generation 1 — evolved from an earlier hypothesis/),
    ).toBeInTheDocument();
    expect(screen.getByText('cluster-7')).toBeInTheDocument();
    expect(screen.getByText('allow')).toBeInTheDocument();

    // Claim-evidence summary counts only this hypothesis's claims (2 of 3),
    // labelled by verdict.
    expect(
      screen.getByText(
        /2 claim\(s\) assessed, 1 supported, 1 unsupported \(speculative\)/,
      ),
    ).toBeInTheDocument();

    expect(screen.getByText('Reasonable and testable.')).toBeInTheDocument();
    expect(screen.getByText('Needs a control arm.')).toBeInTheDocument();

    expect(
      screen.getByText(
        '3 wins and 1 losses across 4 pairwise matches (75% win rate).',
      ),
    ).toBeInTheDocument();

    // The most recent of the two matching matches (by created_at) wins.
    expect(screen.getByText('close')).toBeInTheDocument();
    expect(
      screen.getByText('Multi-turn scientific debate (3 turns)'),
    ).toBeInTheDocument();
    expect(screen.getByText('The latest match rationale.')).toBeInTheDocument();
    expect(
      screen.queryByText('An earlier match rationale.'),
    ).not.toBeInTheDocument();
  });

  it('falls back to placeholder copy when there is no review, match, mechanism, or effect data', () => {
    const hypothesis = makeHypothesis({
      id: 'h1',
      mechanism: null,
      expected_effect: null,
      win_count: 0,
      loss_count: 0,
    });
    render(
      <HypothesisDetail hypothesis={hypothesis} reviews={[]} matches={[]} />,
    );

    expect(
      screen.getByText(
        'Reviewer notes will appear after the review node completes.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText('No full review has been recorded yet.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('No tournament matches have been recorded yet.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('No match rationale is available yet.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Proposed mechanism of action:/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Expected effect:/)).not.toBeInTheDocument();
    expect(screen.queryByText('Outcome:')).not.toBeInTheDocument();
  });
});

describe('SectionsRail', () => {
  it('renders a link for every rail section', () => {
    render(<SectionsRail />);
    for (const label of [
      'Hypothesis overview',
      'Description',
      'Provenance & lineage',
      'Review summary',
      'Full review',
      'Tournament performance',
    ]) {
      expect(
        screen.getByRole('link', {name: new RegExp(label)}),
      ).toBeInTheDocument();
    }
    // "Match summary" is inline-only, not linked from the rail.
    expect(
      screen.queryByRole('link', {name: /Match summary/}),
    ).not.toBeInTheDocument();
  });

  it('prevents default and delegates to smoothScrollToSection when the target exists', async () => {
    const {smoothScrollToSection} = await import('@/lib/smooth_scroll');
    vi.mocked(smoothScrollToSection).mockReturnValue(true);
    render(<SectionsRail />);

    const link = screen.getByRole('link', {name: /Hypothesis overview/});
    const notPrevented = fireEvent.click(link);

    expect(smoothScrollToSection).toHaveBeenCalledWith(
      'hypothesis-overview',
      16,
    );
    // dispatchEvent returns false when a cancelable event's default was
    // prevented.
    expect(notPrevented).toBe(false);
  });

  it('falls through to default navigation when no scroll target is found', async () => {
    const {smoothScrollToSection} = await import('@/lib/smooth_scroll');
    vi.mocked(smoothScrollToSection).mockReturnValue(false);
    render(<SectionsRail />);

    const link = screen.getByRole('link', {name: /Description/});
    const notPrevented = fireEvent.click(link);

    expect(notPrevented).toBe(true);
  });
});

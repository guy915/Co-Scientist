import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import type {ClaimEvidenceRow, MatchRow, Review} from '@/api/runs';
import {makeHypothesis} from '@/test_fixtures';
import {HypothesisDetail, SectionsRail} from './ideas_detail_pane';

vi.mock('@/lib/smooth_scroll', () => ({
  smoothScrollToSection: vi.fn(),
}));

/** A fully-populated hypothesis exercising every detail section. */
function fullHypothesis() {
  return makeHypothesis({
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
}

/** Two reviews: one matching hypothesis h1, one for a different id. */
function matchingReviews(): Review[] {
  return [
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
}

/** Three matches: two involving h1 (older, newer) and one unrelated. */
function orderedMatches(): MatchRow[] {
  return [
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
}

/** Claim evidence: a supported claim, a speculative claim, one unrelated. */
function mixedClaimEvidence(): ClaimEvidenceRow[] {
  return [
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
      claim_role: 'speculative',
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
}

/** Renders the detail pane with the full fixture set. */
function renderFullDetail() {
  render(
    <HypothesisDetail
      hypothesis={fullHypothesis()}
      reviews={matchingReviews()}
      matches={orderedMatches()}
      claimEvidence={mixedClaimEvidence()}
    />,
  );
}

/** A grounded claim with an exact span plus a spanless speculative claim. */
function groundedClaimEvidence(): ClaimEvidenceRow[] {
  return [
    {
      id: 1,
      hypothesis_id: 'h1',
      claim: 'Kinase X inhibition reduces tumor growth.',
      label: 'supports',
      supporting: [
        {
          evidence_id: 'ev-1',
          quote: 'reduces tumor growth in AML',
          start: 18,
          end: 45,
          source: 'pubmed',
          url: 'https://example.org/ev-1',
        },
      ],
      contradicting: [],
      assessor: 'llm:deepseek/deepseek-chat',
    },
    // A speculative claim has no span but remains visibly labeled.
    {
      id: 2,
      hypothesis_id: 'h1',
      claim: 'A speculative claim.',
      label: 'insufficient',
      claim_role: 'speculative',
      supporting: [],
      contradicting: [],
      assessor: 'llm:deepseek/deepseek-chat',
    },
  ];
}

/** Renders the detail pane with only claim evidence populated. */
function renderClaimDetail(claimEvidence: ClaimEvidenceRow[]) {
  render(
    <HypothesisDetail
      hypothesis={makeHypothesis({id: 'h1'})}
      reviews={[]}
      matches={[]}
      claimEvidence={claimEvidence}
    />,
  );
}

it('renders the empty-state placeholder when nothing is selected', () => {
  render(<HypothesisDetail hypothesis={null} reviews={[]} matches={[]} />);
  expect(
    screen.getByText(
      'Select a hypothesis to inspect the review and tournament details.',
    ),
  ).toBeInTheDocument();
});

it('renders the description sections from the selected hypothesis', () => {
  renderFullDetail();

  expect(screen.getByText('A testable statement.')).toBeInTheDocument();
  expect(screen.getByText('A promising idea')).toBeInTheDocument();
  expect(screen.getByText(/Proposed mechanism of action:/)).toBeInTheDocument();
  expect(screen.getByText('A described mechanism.')).toBeInTheDocument();
  expect(screen.getByText(/Expected effect:/)).toBeInTheDocument();
  expect(screen.getByText('A measurable effect.')).toBeInTheDocument();
});

it('surfaces provenance and lineage details', () => {
  renderFullDetail();

  // Provenance & lineage section surfaces origin, generation, cluster, safety.
  expect(
    screen.getByText(/Evolution agent \(refined from a parent\)/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Generation 1 — evolved from an earlier hypothesis/),
  ).toBeInTheDocument();
  expect(screen.getByText('cluster-7')).toBeInTheDocument();
  expect(screen.getByText('allow')).toBeInTheDocument();
});

it("summarizes claim evidence for only this hypothesis's claims", () => {
  renderFullDetail();

  // Claim-evidence summary counts only this hypothesis's claims (2 of 3),
  // labelled by verdict.
  expect(
    screen.getByText(/2 claim\(s\) assessed, 1 supported, 1 speculative/),
  ).toBeInTheDocument();
});

it('renders the matching review and filters out unrelated reviews', () => {
  renderFullDetail();

  expect(screen.getByText('Reasonable and testable.')).toBeInTheDocument();
  expect(screen.getByText('Needs a control arm.')).toBeInTheDocument();
  expect(screen.queryByText('Unrelated.')).not.toBeInTheDocument();
});

it('labels each review row by its reviewer instead of one Full review', () => {
  // Finding D13/E1: the initial, deep, and full/simulation/recurrent
  // results are independent reviews and must stay visibly distinct.
  const hypothesis = makeHypothesis({id: 'h1'});
  const reviews: Review[] = [
    {
      id: 1,
      hypothesis_id: 'h1',
      reviewer_agent: 'review',
      summary: 'Initial review verdict: viable',
      critique: 'The initial peer critique.',
      novelty: null,
      plausibility: null,
      testability: null,
      overall: null,
    },
    {
      id: 2,
      hypothesis_id: 'h1',
      reviewer_agent: 'full_review',
      summary: 'Full review verdict: sound',
      critique: 'The full review critique.',
      novelty: null,
      plausibility: null,
      testability: null,
      overall: null,
    },
    {
      id: 3,
      hypothesis_id: 'h1',
      reviewer_agent: 'simulation_review',
      summary: 'Simulation review verdict: holds',
      critique: 'The simulation critique.',
      novelty: null,
      plausibility: null,
      testability: null,
      overall: null,
    },
    {
      id: 4,
      hypothesis_id: 'h1',
      reviewer_agent: 'deep_verification',
      summary: 'Deep verification verdict: holds',
      critique: 'The deep verification critique.',
      novelty: null,
      plausibility: null,
      testability: null,
      overall: null,
    },
  ];

  render(
    <HypothesisDetail hypothesis={hypothesis} reviews={reviews} matches={[]} />,
  );

  expect(screen.getByText('Initial peer review')).toBeInTheDocument();
  expect(screen.getByText('Full review')).toBeInTheDocument();
  expect(screen.getByText('Simulation review')).toBeInTheDocument();
  expect(screen.getByText('Deep verification')).toBeInTheDocument();
  expect(screen.getByText('The initial peer critique.')).toBeInTheDocument();
  expect(screen.getByText('The full review critique.')).toBeInTheDocument();
  expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
  expect(
    screen.getByText('The deep verification critique.'),
  ).toBeInTheDocument();
});

it('renders tournament stats and the most recent matching match', () => {
  renderFullDetail();

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

it('falls back to placeholder copy when there is no data', () => {
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
    screen.getByText('No review critiques have been recorded yet.'),
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

it('renders a link for every rail section', () => {
  render(<SectionsRail />);
  for (const label of [
    'Hypothesis overview',
    'Description',
    'Provenance & lineage',
    'Review summary',
    'Review critiques',
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

it('delegates to smoothScrollToSection when the target exists', async () => {
  const {smoothScrollToSection} = await import('@/lib/smooth_scroll');
  vi.mocked(smoothScrollToSection).mockReturnValue(true);
  render(<SectionsRail />);

  const link = screen.getByRole('link', {name: /Hypothesis overview/});
  const notPrevented = fireEvent.click(link);

  expect(smoothScrollToSection).toHaveBeenCalledWith(
    'hypothesis-overview',
    16,
    '.idea-detail-pane, .cosci-report-scroll',
  );
  // dispatchEvent returns false when a cancelable event's default was
  // prevented.
  expect(notPrevented).toBe(false);
});

it('falls through to default navigation with no scroll target', async () => {
  const {smoothScrollToSection} = await import('@/lib/smooth_scroll');
  vi.mocked(smoothScrollToSection).mockReturnValue(false);
  render(<SectionsRail />);

  const link = screen.getByRole('link', {name: /Description/});
  const notPrevented = fireEvent.click(link);

  expect(notPrevented).toBe(true);
});

describe('HypothesisDetail claim-evidence provenance', () => {
  it('renders each grounded claim with its quote and source link', () => {
    renderClaimDetail(groundedClaimEvidence());

    // The exact supporting quote is shown...
    expect(screen.getByText(/reduces tumor growth in AML/)).toBeInTheDocument();
    // ...with a link that opens the exact source.
    const link = screen.getByRole('link', {name: /open source/});
    expect(link).toHaveAttribute('href', 'https://example.org/ev-1');
    // The claim remains visible even though no evidence span supports it.
    expect(screen.getByText(/A speculative claim\./)).toBeInTheDocument();
    expect(
      screen.getByText('Speculative — evidence insufficient'),
    ).toBeInTheDocument();
  });

  it('tolerates legacy claim rows that stored a bare passage string', () => {
    renderClaimDetail([
      {
        id: 1,
        hypothesis_id: 'h1',
        claim: 'A supported claim.',
        label: 'supports',
        supporting: ['A legacy supporting passage.'],
        contradicting: [],
        assessor: 'deterministic-v1',
      },
    ]);

    expect(
      screen.getByText(/A legacy supporting passage\./),
    ).toBeInTheDocument();
    // No source link when the legacy row carries no url.
    expect(
      screen.queryByRole('link', {name: /open source/}),
    ).not.toBeInTheDocument();
  });
});

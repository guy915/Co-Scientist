import type {ClaimEvidenceRow, MatchRow, Review} from '@/api/runs';
import {makeHypothesis} from '@/test_fixtures';
import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {smoothScrollToSection} from '@/lib/smooth_scroll';
import {HypothesisDetail, SectionsRail} from './ideas_detail_pane';

vi.mock('@/lib/smooth_scroll', () => ({smoothScrollToSection: vi.fn()}));

function review(over: Partial<Review>): Review {
  return {
    id: 1,
    hypothesis_id: 'h1',
    reviewer_agent: 'reflection',
    summary: 'Reasonable and testable.',
    critique: 'Needs a control arm.',
    novelty: null,
    plausibility: null,
    testability: null,
    overall: null,
    ...over,
  };
}

function match(id: number, over: Partial<MatchRow>): MatchRow {
  return {
    id,
    iteration: 1,
    winner_id: 'h1',
    loser_id: 'h2',
    winner_elo_before: 1200,
    winner_elo_after: 1210,
    loser_elo_before: 1200,
    loser_elo_after: 1190,
    created_at: 100,
    tier: 'strong',
    debate_turns: 1,
    rationale: '',
    debate_transcript: null,
    ...over,
  };
}

function claim(id: number, over: Partial<ClaimEvidenceRow>): ClaimEvidenceRow {
  return {
    id,
    hypothesis_id: 'h1',
    claim: 'A claim.',
    label: 'supports',
    supporting: [],
    contradicting: [],
    assessor: 'deterministic-v1',
    ...over,
  };
}

function renderDetail(
  props: Partial<Parameters<typeof HypothesisDetail>[0]> = {},
) {
  return render(
    <HypothesisDetail
      hypothesis={makeHypothesis({id: 'h1'})}
      reviews={[]}
      matches={[]}
      {...props}
    />,
  );
}

describe('ideas detail pane', () => {
  it('invites a selection when nothing is selected', () => {
    renderDetail({hypothesis: null});

    expect(
      screen.getByText(
        'Select a hypothesis to inspect the review and tournament details.',
      ),
    ).toBeInTheDocument();
  });

  it('shows the idea, its lineage, only its own reviews and claims, and its newest matches first', () => {
    renderDetail({
      hypothesis: makeHypothesis({
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
      }),
      reviews: [
        review({}),
        review({id: 2, hypothesis_id: 'other', summary: 'Unrelated.'}),
      ],
      matches: [
        match(1, {
          iteration: 1,
          created_at: 100,
          rationale: 'An earlier match rationale.',
        }),
        match(2, {
          iteration: 2,
          created_at: 200,
          winner_id: 'h3',
          loser_id: 'h1',
          tier: 'close',
          debate_turns: 3,
          rationale: 'The latest match rationale.',
        }),
        match(3, {
          winner_id: 'other-a',
          loser_id: 'other-b',
          created_at: 300,
          rationale: 'Unrelated match.',
        }),
      ],
      claimEvidence: [
        claim(1, {claim: 'A supported claim.', supporting: ['A passage.']}),
        claim(2, {
          claim: 'An unsupported claim.',
          label: 'insufficient',
          claim_role: 'speculative',
        }),
        claim(3, {hypothesis_id: 'other', label: 'contradicts'}),
      ],
    });

    for (const text of [
      'A testable statement.',
      'A described mechanism.',
      'A measurable effect.',
      'cluster-7',
      'allow',
      'Reasonable and testable.',
      'Needs a control arm.',
      /Evolution agent \(refined from a parent\)/,
      /Generation 1 — evolved from an earlier hypothesis/,
      /2 claim\(s\) assessed, 1 supported, 1 speculative/,
      '3 wins and 1 losses across 4 pairwise matches (75% win rate).',
      'Iteration 2 · close',
      'Multi-turn scientific debate (3 turns)',
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.queryByText('Unrelated.')).not.toBeInTheDocument();
    expect(screen.queryByText('Unrelated match.')).not.toBeInTheDocument();
    expect(
      screen
        .getByText('The latest match rationale.')
        .compareDocumentPosition(
          screen.getByText('An earlier match rationale.'),
        ),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('labels each review row by its reviewer instead of one Full review', () => {
    renderDetail({
      reviews: [
        'review',
        'full_review',
        'simulation_review',
        'deep_verification',
      ].map((agent, index) =>
        review({id: index, reviewer_agent: agent, critique: `${agent} note`}),
      ),
    });

    for (const label of [
      'Initial peer review',
      'Full review',
      'Simulation review',
      'Deep verification',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText('deep_verification note')).toBeInTheDocument();
  });

  it('falls back to placeholder copy when there is no data', () => {
    renderDetail({
      hypothesis: makeHypothesis({
        id: 'h1',
        mechanism: null,
        expected_effect: null,
        win_count: 0,
        loss_count: 0,
      }),
    });

    for (const text of [
      'Reviewer notes will appear after the review node completes.',
      'No review critiques have been recorded yet.',
      'No tournament matches have been recorded yet.',
      'No match rationale is available yet.',
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(
      screen.queryByText(/Proposed mechanism of action:/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Expected effect:/)).not.toBeInTheDocument();
  });

  it('shows each grounded claim with its quote and source link, tolerating legacy bare passages', () => {
    renderDetail({
      claimEvidence: [
        claim(1, {
          claim: 'Kinase X inhibition reduces tumor growth.',
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
        }),
        claim(2, {
          claim: 'A speculative claim.',
          label: 'insufficient',
          claim_role: 'speculative',
        }),
        claim(3, {supporting: ['A legacy supporting passage.']}),
      ],
    });

    expect(screen.getByText(/reduces tumor growth in AML/)).toBeInTheDocument();
    expect(screen.getByRole('link', {name: /open source/})).toHaveAttribute(
      'href',
      'https://example.org/ev-1',
    );
    expect(
      screen.getByText('Speculative — evidence insufficient'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/A legacy supporting passage\./),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('link', {name: /open source/})).toHaveLength(1);
  });

  it('shows the idea’s losses and wins with Elo change and expandable stored debates', () => {
    renderDetail({
      matches: [
        match(10, {
          iteration: 1,
          loser_id: 'opponent-old',
          winner_elo_after: 1218,
          loser_elo_after: 1182,
          rationale: 'Historical win rationale.',
          created_at: 300,
        }),
        match(11, {
          iteration: 3,
          winner_id: 'opponent-new',
          loser_id: 'h1',
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
              {turn: 1, favored: '1', text: 'First comparison.', first: '1'},
              {turn: 2, favored: '2', text: 'Second comparison.', first: '2'},
            ],
          }),
        }),
      ],
    });

    expect(screen.getByText('Loss against opponent-new')).toBeInTheDocument();
    expect(screen.getByText('Win against opponent-old')).toBeInTheDocument();
    const eloLabels = screen.getAllByText('Elo change:');
    expect(eloLabels[0].parentElement).toHaveTextContent('Elo change: -14');
    expect(eloLabels[1].parentElement).toHaveTextContent('Elo change: +18');

    const summary = screen.getByText('Debate transcript (2 turns)');
    const disclosure = summary.closest('details');
    expect(disclosure).not.toHaveAttribute('open');
    fireEvent.click(summary);
    expect(disclosure).toHaveAttribute('open');
    expect(screen.getByText('Turn 1:').parentElement).toHaveTextContent(
      'selected hypothesis was presented as Hypothesis 1; this turn favored it.',
    );
    expect(screen.getByText('Turn 2:').parentElement).toHaveTextContent(
      'selected hypothesis was presented as Hypothesis 2; this turn favored the opponent.',
    );
  });
});

describe('structured review findings (detail_json)', () => {
  function renderReview(detail_json?: string | null) {
    renderDetail({
      reviews: [
        review({
          reviewer_agent: 'simulation_review',
          critique: 'The simulation critique.',
          detail_json,
        }),
      ],
    });
  }

  it("surfaces the simulation review's failure points and decisive step, and the full review's verdict", () => {
    renderReview(
      JSON.stringify({
        failure_points: ['Off-target binding at high dose', 'Assay noise'],
        decisive_step: 'The dose-response titration in week 2',
      }),
    );
    expect(screen.getAllByText('Failure point:')).toHaveLength(2);
    expect(screen.getByText('Assay noise')).toBeInTheDocument();
    expect(
      screen.getByText('The dose-response titration in week 2'),
    ).toBeInTheDocument();
    expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
  });

  it("surfaces the full review's verdict, which never overlaps its critique", () => {
    renderDetail({
      reviews: [
        review({
          reviewer_agent: 'full_review',
          critique: 'The full review critique.',
          detail_json: JSON.stringify({
            go_no_go: 'Go — pursue wet-lab validation',
            time_to_verdict: '2-4 weeks',
          }),
        }),
      ],
    });

    expect(
      screen.getByText('Go — pursue wet-lab validation'),
    ).toBeInTheDocument();
    expect(screen.getByText('2-4 weeks')).toBeInTheDocument();
    expect(screen.getByText('The full review critique.')).toBeInTheDocument();
  });

  it.each([
    ['a row that predates the column', undefined],
    ['a null detail_json', null],
    ['unparseable detail_json', '{not valid json'],
    ['detail_json that is not an object', '[1,2,3]'],
  ])('renders only the critique for %s', (_name, detail) => {
    renderReview(detail);

    expect(screen.queryByText('Decisive step:')).not.toBeInTheDocument();
    expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
  });

  it('coerces a wrong-typed failure_points/decisive_step instead of crashing', () => {
    renderReview(
      JSON.stringify({
        failure_points: 'A single point, not an array',
        decisive_step: {summary: 'An object instead of a string'},
      }),
    );

    expect(
      screen.getByText('A single point, not an array'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('An object instead of a string'),
    ).toBeInTheDocument();
  });
});

describe('sections rail', () => {
  it('scrolls smoothly when the section exists and leaves the link alone otherwise', () => {
    render(<SectionsRail />);
    const link = screen.getByRole('link', {name: /Description/});

    vi.mocked(smoothScrollToSection).mockReturnValue(true);
    expect(fireEvent.click(link)).toBe(false);

    vi.mocked(smoothScrollToSection).mockReturnValue(false);
    expect(fireEvent.click(link)).toBe(true);
  });
});

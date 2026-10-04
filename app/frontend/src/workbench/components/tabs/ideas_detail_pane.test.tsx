import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import type {ClaimEvidenceRow, MatchRow, Review} from '@/api/runs';
import {makeHypothesis} from '@/test_fixtures';
import {HypothesisDetail, SectionsRail} from './ideas_detail_pane';

vi.mock('@/lib/smooth_scroll', () => ({
  smoothScrollToSection: vi.fn(),
}));

describe('ideas detail pane', () => {
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

  function orderedMatches(): MatchRow[] {
    return [
      {
        id: 1,
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
        rationale: 'An earlier match rationale.',
        debate_transcript: null,
      },
      {
        id: 2,
        iteration: 2,
        winner_id: 'h3',
        loser_id: 'h1',
        winner_elo_before: 1210,
        winner_elo_after: 1220,
        loser_elo_before: 1190,
        loser_elo_after: 1180,
        created_at: 200,
        tier: 'close',
        debate_turns: 3,
        rationale: 'The latest match rationale.',
        debate_transcript: null,
      },
      {
        id: 3,
        iteration: 2,
        winner_id: 'other-a',
        loser_id: 'other-b',
        winner_elo_before: 1200,
        winner_elo_after: 1210,
        loser_elo_before: 1200,
        loser_elo_after: 1190,
        created_at: 300,
        tier: 'strong',
        debate_turns: 1,
        rationale: 'Unrelated match.',
        debate_transcript: null,
      },
    ];
  }

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
    expect(
      screen.getByText(/Proposed mechanism of action:/),
    ).toBeInTheDocument();
    expect(screen.getByText('A described mechanism.')).toBeInTheDocument();
    expect(screen.getByText(/Expected effect:/)).toBeInTheDocument();
    expect(screen.getByText('A measurable effect.')).toBeInTheDocument();
  });

  it('surfaces provenance and lineage details', () => {
    renderFullDetail();

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
      <HypothesisDetail
        hypothesis={hypothesis}
        reviews={reviews}
        matches={[]}
      />,
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

  it('renders tournament stats and match history newest first', () => {
    renderFullDetail();

    expect(
      screen.getByText(
        '3 wins and 1 losses across 4 pairwise matches (75% win rate).',
      ),
    ).toBeInTheDocument();

    expect(screen.getByText('Iteration 2 · close')).toBeInTheDocument();
    expect(screen.getByText('Iteration 1 · strong')).toBeInTheDocument();
    expect(
      screen.getByText('Multi-turn scientific debate (3 turns)'),
    ).toBeInTheDocument();
    const latestRationale = screen.getByText('The latest match rationale.');
    const olderRationale = screen.getByText('An earlier match rationale.');
    expect(latestRationale.compareDocumentPosition(olderRationale)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
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
    // dispatchEvent returns false when a cancelable default was prevented.
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

      expect(
        screen.getByText(/reduces tumor growth in AML/),
      ).toBeInTheDocument();
      const link = screen.getByRole('link', {name: /open source/});
      expect(link).toHaveAttribute('href', 'https://example.org/ev-1');
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
      expect(
        screen.queryByRole('link', {name: /open source/}),
      ).not.toBeInTheDocument();
    });
  });

  it('keeps public demo outcomes readable without exposing submission controls', () => {
    render(
      <HypothesisDetail
        hypothesis={fullHypothesis()}
        runId="demo-run"
        isDemo
        reviews={[]}
        matches={[]}
        onRefreshOutcomes={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('heading', {name: 'Scientist-recorded observations'}),
    ).toBeVisible();
    expect(
      screen.getByRole('button', {name: 'Refresh observations'}),
    ).toBeVisible();
    expect(
      screen.queryByRole('group', {name: 'Record an observation'}),
    ).not.toBeInTheDocument();
  });
});

describe('ideas detail match history', () => {
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
});

describe('ideas detail review findings', () => {
  describe('HypothesisDetail structured review findings (detail_json)', () => {
    function baseReview(overrides: Partial<Review>): Review {
      return {
        id: 1,
        hypothesis_id: 'h1',
        reviewer_agent: 'simulation_review',
        summary: 'Simulation review verdict: partially_holds',
        critique: 'The simulation critique.',
        novelty: null,
        plausibility: null,
        testability: null,
        overall: null,
        ...overrides,
      };
    }

    function renderReview(review: Review) {
      render(
        <HypothesisDetail
          hypothesis={makeHypothesis({id: 'h1'})}
          reviews={[review]}
          matches={[]}
        />,
      );
    }

    it("surfaces the simulation review's named failure points and decisive step above its critique", () => {
      renderReview(
        baseReview({
          detail_json: JSON.stringify({
            failure_points: [
              'Off-target binding at high dose',
              'Assay noise masks the effect',
            ],
            decisive_step: 'The dose-response titration in week 2',
          }),
        }),
      );

      expect(screen.getAllByText('Failure point:')).toHaveLength(2);
      expect(
        screen.getByText('Off-target binding at high dose'),
      ).toBeInTheDocument();
      expect(
        screen.getByText('Assay noise masks the effect'),
      ).toBeInTheDocument();
      expect(screen.getByText('Decisive step:')).toBeInTheDocument();
      expect(
        screen.getByText('The dose-response titration in week 2'),
      ).toBeInTheDocument();
      expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
    });

    it("surfaces the full review's Go/No-Go verdict, which never overlaps its critique", () => {
      renderReview(
        baseReview({
          reviewer_agent: 'full_review',
          critique: 'The full review critique.',
          detail_json: JSON.stringify({
            go_no_go: 'Go — pursue wet-lab validation',
            time_to_verdict: '2-4 weeks',
          }),
        }),
      );

      expect(screen.getByText('Verdict:')).toBeInTheDocument();
      expect(
        screen.getByText('Go — pursue wet-lab validation'),
      ).toBeInTheDocument();
      expect(screen.getByText('Time to verdict:')).toBeInTheDocument();
      expect(screen.getByText('2-4 weeks')).toBeInTheDocument();
      expect(screen.getByText('The full review critique.')).toBeInTheDocument();
    });

    it('renders no structured block for a row that predates the column', () => {
      // Rows written before detail_json existed legitimately omit it.
      renderReview(baseReview({}));

      expect(screen.queryByText('Decisive step:')).not.toBeInTheDocument();
      expect(screen.queryByText('Verdict:')).not.toBeInTheDocument();
      expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
    });

    it('renders no structured block for a null detail_json', () => {
      renderReview(baseReview({detail_json: null}));

      expect(screen.queryByText('Decisive step:')).not.toBeInTheDocument();
      expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
    });

    it('degrades unparseable detail_json without crashing', () => {
      renderReview(baseReview({detail_json: '{not valid json'}));

      expect(screen.queryByText('Decisive step:')).not.toBeInTheDocument();
      expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
    });

    it('degrades detail_json that parses to a non-object without crashing', () => {
      renderReview(baseReview({detail_json: '[1,2,3]'}));

      expect(screen.queryByText('Decisive step:')).not.toBeInTheDocument();
      expect(screen.getByText('The simulation critique.')).toBeInTheDocument();
    });

    it('coerces a wrong-typed failure_points/decisive_step instead of crashing', () => {
      // json_object mode does not enforce field types.
      renderReview(
        baseReview({
          detail_json: JSON.stringify({
            failure_points: 'A single point, not an array',
            decisive_step: {summary: 'An object instead of a string'},
          }),
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
});

import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import type {Review} from '@/api/runs';
import {makeHypothesis} from '@/test_fixtures';
import {HypothesisDetail} from './ideas_detail_pane';

// Split out of ideas_detail_pane.test.tsx to keep that file under the
// repo's 500-line ceiling.
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
    // The prose critique still renders in full alongside the structure.
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
    // No detail_json key at all -- the shape every row carried before the
    // column existed.
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
    // json_object mode carries no schema enforcement: an array field can
    // arrive as a bare string, and a string field as an object.
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

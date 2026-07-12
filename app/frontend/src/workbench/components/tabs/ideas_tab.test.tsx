import {describe, it, expect, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {IdeasTab} from './ideas_tab';
import type {Hypothesis, Review} from '@/api/runs';
import {makeHypothesis} from '@/test-fixtures';

const {addScientistHypothesis, addScientistReview} = vi.hoisted(() => ({
  addScientistHypothesis: vi.fn(),
  addScientistReview: vi.fn(),
}));
vi.mock('@/api/runs', () => ({
  addScientistHypothesis: (...args: unknown[]) =>
    addScientistHypothesis(...args),
  addScientistReview: (...args: unknown[]) => addScientistReview(...args),
}));

describe('IdeasTab', () => {
  it('shows the empty state when there are no hypotheses', () => {
    render(<IdeasTab hypotheses={[]} reviews={[]} />);
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
    render(<IdeasTab hypotheses={hypotheses} reviews={[]} />);
    expect(screen.getAllByText('High-ranked idea')[0]).toBeInTheDocument();
    expect(screen.getByText('Low-ranked idea')).toBeInTheDocument();
    // Default sort is by Elo descending; the higher Elo badge is rendered.
    expect(screen.getByText('Elo rating: 1300')).toBeInTheDocument();
    expect(screen.queryByText('80% wins')).not.toBeInTheDocument();

    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('High-ranked idea');
    expect(rows[1]).toHaveTextContent('Low-ranked idea');
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
        reviews={reviews}
      />,
    );
    expect(screen.getByText('Review summary')).toBeInTheDocument();
    expect(screen.getByText('Full review')).toBeInTheDocument();
    expect(screen.getByText('Reasonable.')).toBeInTheDocument();
    expect(screen.getByText('Needs a control arm.')).toBeInTheDocument();
    expect(screen.queryByText('Full legacy detail')).not.toBeInTheDocument();
  });

  it('renders persisted proximity edges as an inspectable idea landscape', () => {
    render(
      <IdeasTab
        hypotheses={[
          makeHypothesis({id: 'h1', title: 'First connected idea'}),
          makeHypothesis({id: 'h2', title: 'Second connected idea'}),
        ]}
        reviews={[]}
        proximity={[
          {
            id: 1,
            run_id: 'run-1',
            source_hypothesis_id: 'h1',
            target_hypothesis_id: 'h2',
            similarity: 0.85,
            degree: 'high',
            cluster_id: 'cluster-1',
            method: 'llm_cluster_pairwise_graph',
            version: '1',
            model: 'fixture-model',
            updated_at: 1234,
          },
        ]}
      />,
    );
    expect(
      screen.getByRole('region', {name: 'Idea landscape'}),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', {
        name: '2 ideas connected by 1 similarity links',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', {name: 'Open idea 1: First connected idea'}),
    ).toBeInTheDocument();
  });

  it('submits scientist hypotheses and reviews from the Ideas journey', async () => {
    addScientistHypothesis.mockResolvedValue({
      admitted: true,
      id: 'manual-1',
      safety: {outcome: 'allowed'},
    });
    addScientistReview.mockResolvedValue({recorded: true});
    const changed = vi.fn();
    render(
      <IdeasTab
        runId="run-1"
        hypotheses={[makeHypothesis({id: 'h1', title: 'Selected idea'})]}
        reviews={[]}
        onScientistInputChanged={changed}
      />,
    );

    fireEvent.click(screen.getByRole('button', {name: 'Add your hypothesis'}));
    const hypothesisForm = screen.getByLabelText('Hypothesis').closest('form')!;
    fireEvent.change(screen.getAllByLabelText('Researcher name')[0], {
      target: {value: 'Dr Curie'},
    });
    fireEvent.change(screen.getByLabelText('Hypothesis'), {
      target: {value: 'A scientist-authored mechanism.'},
    });
    fireEvent.submit(hypothesisForm);
    await waitFor(() => expect(addScientistHypothesis).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', {name: 'Review selected idea'}));
    const critique = screen.getByLabelText('Scientific critique');
    fireEvent.change(screen.getAllByLabelText('Researcher name')[1], {
      target: {value: 'Dr Curie'},
    });
    fireEvent.change(critique, {
      target: {value: 'Add a falsification control.'},
    });
    fireEvent.submit(critique.closest('form')!);
    await waitFor(() => expect(addScientistReview).toHaveBeenCalled());
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
  });
});

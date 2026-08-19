import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it} from 'vitest';
import {type CodeVariant} from '@/api/runs';
import {runningBest} from '../components/tabs/variants_plot';
import {VariantsView} from './run_detail_variants';

function variant(over: Partial<CodeVariant>): CodeVariant {
  return {
    id: `v${over.ordinal ?? 1}`,
    run_id: 'r1',
    parent_id: null,
    generation: 0,
    ordinal: 1,
    operator: null,
    rationale: '',
    diff: '',
    source: {'main.py': 'x = 1'},
    created_by_agent: 'discovery.seed',
    created_at: 0,
    status: 'ok',
    fitness: null,
    is_best_so_far: false,
    duration_seconds: null,
    stages: [],
    objective_values: [over.fitness ?? null],
    behaviour: {},
    ...over,
  };
}

describe('runningBest', () => {
  it('holds the record flat across attempts that did not beat it', () => {
    const points = runningBest([
      variant({ordinal: 1, fitness: 1}),
      variant({ordinal: 2, fitness: 0.5}),
      variant({ordinal: 3, fitness: 4}),
    ]);
    expect(points.map(p => p.best)).toEqual([1, 1, 4]);
    expect(points.map(p => p.isRecord)).toEqual([true, false, true]);
  });

  it('advances the attempt axis across variants that never scored', () => {
    // The whole point of plotting against attempt number: a run that took
    // four tries to improve must not look like it took two.
    const points = runningBest([
      variant({ordinal: 1, fitness: 1}),
      variant({ordinal: 2, fitness: null, status: 'failed'}),
      variant({ordinal: 3, fitness: null, status: 'no_metrics'}),
      variant({ordinal: 4, fitness: 2}),
    ]);
    expect(points.map(p => p.ordinal)).toEqual([1, 2, 3, 4]);
    expect(points.map(p => p.best)).toEqual([1, 1, 1, 2]);
  });

  it('starts only once something has scored', () => {
    expect(
      runningBest([variant({ordinal: 1, fitness: null, status: 'failed'})]),
    ).toEqual([]);
  });

  it('never treats an unscored variant as a record', () => {
    const points = runningBest([
      variant({ordinal: 1, fitness: -5}),
      variant({ordinal: 2, fitness: null}),
    ]);
    expect(points.map(p => p.isRecord)).toEqual([true, false]);
  });
});

describe('VariantsView', () => {
  it('lists every attempt, failures included, in attempt order', () => {
    render(
      <VariantsView
        variants={[
          variant({ordinal: 1, fitness: 1}),
          variant({ordinal: 2, fitness: null, status: 'failed'}),
          variant({ordinal: 3, fitness: 4, operator: 'algorithm_swap'}),
        ]}
      />,
    );
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('algorithm swap')).toBeInTheDocument();
  });

  it('shows a dash for an unscored variant, never a zero', () => {
    // A crashed attempt and an attempt that genuinely scored zero are
    // different facts; rendering them alike implies the crash was merely
    // a bad result.
    render(
      <VariantsView
        variants={[variant({ordinal: 1, fitness: null, status: 'failed'})]}
      />,
    );
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('reports the best score and which attempt reached it', () => {
    render(
      <VariantsView
        variants={[
          variant({ordinal: 1, fitness: 1}),
          variant({ordinal: 2, fitness: 9}),
          variant({ordinal: 3, fitness: 4}),
        ]}
      />,
    );
    expect(
      screen.getByText(/Best score 9, reached on attempt 2 of 3/),
    ).toBeInTheDocument();
  });

  it('says so plainly when nothing has scored', () => {
    render(
      <VariantsView
        variants={[variant({ordinal: 1, fitness: null, status: 'failed'})]}
      />,
    );
    expect(screen.getByText('1 attempts, none scored.')).toBeInTheDocument();
    expect(
      screen.getByText('No attempt has produced a score yet.'),
    ).toBeInTheDocument();
  });

  it('reveals the edit and the captured error on demand', async () => {
    render(
      <VariantsView
        variants={[
          variant({
            ordinal: 1,
            fitness: null,
            status: 'failed',
            operator: 'repair',
            diff: '*** Begin Patch',
            artifacts: {stderr: 'ZeroDivisionError'},
          }),
        ]}
      />,
    );
    expect(screen.queryByText('ZeroDivisionError')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', {name: /repair/}));
    expect(screen.getByText('ZeroDivisionError')).toBeInTheDocument();
    expect(screen.getByText('*** Begin Patch')).toBeInTheDocument();
  });

  it('calls the seed what it is rather than leaving the cell blank', () => {
    render(<VariantsView variants={[variant({ordinal: 1, fitness: 1})]} />);
    expect(screen.getByText('seed')).toBeInTheDocument();
  });
});

describe('VariantsView, multi-objective', () => {
  const objectives = [
    {metric: 'accuracy', direction: 'maximize'},
    {metric: 'latency', direction: 'minimize'},
  ];

  it('shows the trade-off only when there is more than one objective', () => {
    const {rerender} = render(
      <VariantsView
        variants={[variant({ordinal: 1, fitness: 1})]}
        objectives={[{metric: 'score', direction: 'maximize'}]}
      />,
    );
    expect(screen.queryByText('The trade-off')).not.toBeInTheDocument();
    rerender(
      <VariantsView
        variants={[
          variant({
            ordinal: 1,
            fitness: 1,
            objective_values: [1, -2],
            is_pareto_optimal: true,
          }),
        ]}
        objectives={objectives}
      />,
    );
    expect(screen.getByText('The trade-off')).toBeInTheDocument();
  });

  it('says there is no single best when objectives compete', () => {
    render(
      <VariantsView
        variants={[
          variant({ordinal: 1, fitness: 9, objective_values: [9, -5]}),
          variant({ordinal: 2, fitness: 1, objective_values: [1, -1]}),
        ]}
        objectives={objectives}
      />,
    );
    expect(screen.getByText(/no single best program/)).toBeInTheDocument();
  });

  it('names the primary objective in the score summary', () => {
    render(
      <VariantsView
        variants={[variant({ordinal: 1, fitness: 4})]}
        objectives={objectives}
      />,
    );
    expect(screen.getByText(/Best accuracy 4/)).toBeInTheDocument();
  });

  it('warns when many cells hide one dominant pile', () => {
    // A high cell count reads as exploration unless the evenness is
    // shown beside it -- the false reassurance the archive removes.
    render(
      <VariantsView
        variants={[variant({ordinal: 1, fitness: 1})]}
        nichesOccupied={6}
        nicheEvenness={0.1}
      />,
    );
    expect(
      screen.getByText(/Most attempts landed in one of them/),
    ).toBeInTheDocument();
  });

  it('stays quiet when the spread is genuinely even', () => {
    render(
      <VariantsView
        variants={[variant({ordinal: 1, fitness: 1})]}
        nichesOccupied={6}
        nicheEvenness={0.9}
      />,
    );
    expect(screen.queryByText(/Most attempts landed/)).not.toBeInTheDocument();
  });

  it('reports how much of the behaviour space was explored', () => {
    // Without this a reader sees a score creeping up and cannot tell
    // whether the run explored or polished one idea.
    render(
      <VariantsView
        variants={[variant({ordinal: 1, fitness: 1})]}
        nichesOccupied={4}
      />,
    );
    expect(
      screen.getByText(/Explored 4 distinct approaches/),
    ).toBeInTheDocument();
  });

  it('does not badge the front twice when it is also the best', () => {
    // With one objective the front is the best, and two badges for one
    // fact reads as two findings.
    render(
      <VariantsView
        variants={[
          variant({
            ordinal: 1,
            fitness: 5,
            is_best_so_far: true,
            is_pareto_optimal: true,
          }),
        ]}
      />,
    );
    expect(screen.getByText('best so far')).toBeInTheDocument();
    expect(screen.queryByText('best trade-off')).not.toBeInTheDocument();
  });

  it('badges a variant that leads only on the second objective', () => {
    render(
      <VariantsView
        variants={[
          variant({
            ordinal: 1,
            fitness: 1,
            objective_values: [1, -1],
            is_pareto_optimal: true,
          }),
        ]}
        objectives={objectives}
      />,
    );
    expect(screen.getByText('best trade-off')).toBeInTheDocument();
  });
});

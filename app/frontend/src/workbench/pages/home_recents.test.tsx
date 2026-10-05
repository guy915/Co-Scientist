import {describe, expect, it, afterEach, vi} from 'vitest';
import type {Run, RunStatus} from '@/api/runs';
import {makeRun} from '@/test_fixtures';
import {
  formatHomeRunTimeChip,
  homeRunStepIndex,
  HomeRecentsPanel,
  RunStepFlow,
} from './chat_home_stage';
import {act, render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';

describe('home recents data', () => {
  const NOW = 10_000;

  it('shows total time for a completed run with valid timestamps', () => {
    const run = makeRun({
      status: 'completed',
      created_at: 1000,
      completed_at: 1000 + 3600,
    });
    expect(formatHomeRunTimeChip(run, NOW)).toBe('Total time: 1 hour');
  });

  it('shows the raw capitalized status for an in-between run', () => {
    const statuses: RunStatus[] = ['draft', 'failed', 'cancelled', 'blocked'];
    for (const status of statuses) {
      const run = makeRun({status});
      expect(formatHomeRunTimeChip(run, NOW)).toBe(
        `Status: ${status.charAt(0).toUpperCase()}${status.slice(1)}`,
      );
    }
  });

  const ENGINE_TASK_PHASES: [string, number | null][] = [
    ['engine.bootstrap', 1],
    ['engine.node.supervisor', 1],
    ['engine.node.orchestrator', null],
    ['engine.node.literature_review', 2],
    ['engine.node.generate', 2],
    ['engine.fanout.generation.strategy', 2],
    ['engine.fanout.generation.aggregate', 2],
    ['engine.node.reflection', 3],
    ['engine.node.comprehensive_reflection', 3],
    ['engine.node.review', 3],
    ['engine.node.deep_verification', 3],
    ['engine.node.safety_screen', 3],
    ['engine.node.proximity', 4],
    ['engine.fanout.reflection.item', 3],
    ['engine.fanout.reflection.aggregate', 3],
    ['engine.fanout.review.item', 3],
    ['engine.fanout.review.aggregate', 3],
    ['engine.fanout.verification.item', 3],
    ['engine.fanout.verification.aggregate', 3],
    ['engine.node.ranking', 4],
    ['engine.ranking.match', 4],
    ['engine.ranking.finalize', 4],
    ['engine.node.evolve', 4],
    ['engine.node.meta_review', 4],
    ['engine.node.research_overview', 4],
    ['engine.finalize', 4],
  ];

  function activeTask(active_task: string | null): Partial<Run> {
    return {
      status: 'running',
      execution_progress: {
        determinate: false,
        completed_tasks: 1,
        total_tasks: 4,
        fraction: null,
        active_task,
        queued_tasks: 2,
      },
    };
  }

  it('maps queued to step 1 and synthesizing to step 4 directly', () => {
    expect(homeRunStepIndex(makeRun({status: 'queued'}))).toBe(1);
    expect(homeRunStepIndex(makeRun({status: 'synthesizing'}))).toBe(4);
  });

  it('derives the phase from the engine provider’s active durable task', () => {
    for (const [task, phase] of ENGINE_TASK_PHASES) {
      expect(homeRunStepIndex(makeRun(activeTask(task))), task).toBe(phase);
    }
  });

  it('derives the phase from a reported pipeline-stage event', () => {
    const cases: [string, number][] = [
      ['supervisor.plan', 1],
      ['literature_review', 2],
      ['generate', 2],
      ['reflection', 3],
      ['proximity', 4],
      ['ranking', 4],
      ['evolve', 4],
      ['meta_review', 4],
      ['deep_verification', 3],
      ['research_overview', 4],
    ];
    for (const [latest_stage, phase] of cases) {
      expect(
        homeRunStepIndex(makeRun({status: 'running', latest_stage})),
        latest_stage,
      ).toBe(phase);
    }
  });

  it('reports no phase for a running run that reports no progress yet', () => {
    expect(
      homeRunStepIndex(makeRun({status: 'running', latest_stage: null})),
    ).toBeNull();
    expect(homeRunStepIndex(makeRun(activeTask(null)))).toBeNull();
    expect(homeRunStepIndex(makeRun(activeTask('engine.node.unknown')))).toBe(
      null,
    );
  });

  it('re-enters an earlier phase when the run cycles back to it', () => {
    // A later engine cycle legitimately returns to generation.
    expect(homeRunStepIndex(makeRun(activeTask('engine.ranking.match')))).toBe(
      4,
    );
    expect(
      homeRunStepIndex(
        makeRun(activeTask('engine.fanout.generation.strategy')),
      ),
    ).toBe(2);
  });
});

describe('home recents elapsed', () => {
  const START_MS = Date.UTC(2026, 0, 1);

  function renderPanel(createdAtSeconds: number) {
    const run = makeRun({
      status: 'running',
      created_at: createdAtSeconds,
      updated_at: createdAtSeconds,
      completed_at: null,
    });
    return render(
      <MemoryRouter>
        <HomeRecentsPanel
          runs={[run]}
          showAll={false}
          onToggleShowAll={() => {}}
        />
      </MemoryRouter>,
    );
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it('advances an active run’s elapsed chip as the clock ticks', () => {
    vi.useFakeTimers();
    vi.setSystemTime(START_MS);
    renderPanel(START_MS / 1000 - 30);

    expect(screen.getByText('Time elapsed: < 1 minute')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText('Time elapsed: 2 minutes')).toBeInTheDocument();
  });
});

describe('home recents run steps', () => {
  function runOn(active_task: string): Run {
    return makeRun({
      status: 'running',
      latest_stage: null,
      execution_progress: {
        determinate: false,
        completed_tasks: 1,
        total_tasks: 2,
        fraction: null,
        active_task,
        queued_tasks: 1,
      },
    });
  }

  function shownPhases(): (string | null | undefined)[] {
    return [...document.querySelectorAll('.reference-run-step-icon')].map(
      icon =>
        icon.parentElement?.querySelector('.reference-run-step-label')
          ?.textContent,
    );
  }

  it('reveals only the phases the run has actually reached', () => {
    render(<RunStepFlow run={runOn('engine.node.supervisor')} />);
    expect(shownPhases()).toEqual(['Exploring focus areas']);
    expect(screen.getByText('In Progress')).toBeInTheDocument();
  });

  it('reveals each further phase as the run reaches it', () => {
    const {rerender} = render(
      <RunStepFlow run={runOn('engine.node.generate')} />,
    );
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
    ]);

    rerender(<RunStepFlow run={runOn('engine.ranking.match')} />);
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
      'Reviewing hypotheses',
      'Playing tournament',
    ]);
  });

  it('carries one spinner, on the In Progress row', () => {
    render(<RunStepFlow run={runOn('engine.fanout.reflection.item')} />);
    expect(
      document.querySelectorAll('.reference-run-step-spinner'),
    ).toHaveLength(1);
    const row = document
      .querySelector('.reference-run-step-spinner')
      ?.closest('.reference-run-step');
    expect(row?.querySelector('.reference-run-step-icon')).toBeNull();
    expect(row?.textContent).toContain('In Progress');
  });

  it('moves back when the run reports an earlier phase', () => {
    const {rerender} = render(
      <RunStepFlow run={runOn('engine.ranking.match')} />,
    );
    expect(shownPhases()).toHaveLength(4);

    rerender(<RunStepFlow run={runOn('engine.fanout.review.item')} />);
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
      'Reviewing hypotheses',
    ]);
  });
});

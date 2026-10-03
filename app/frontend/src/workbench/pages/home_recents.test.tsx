import {describe, expect, it, afterEach, vi} from 'vitest';
import type {Run, RunStatus} from '@/api/runs';
import {makeRun} from '@/test_fixtures';
import {
  formatHomeRunDate,
  formatHomeRunTimeChip,
  homeRunStepIndex,
  HomeRecentsPanel,
  RunStepFlow,
} from './chat_home_stage';
import {act, render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';

describe('home recents data', () => {
  describe('formatHomeRunDate', () => {
    it('formats a unix-seconds timestamp as a long localized date', () => {
      const formatted = formatHomeRunDate(1_700_000_000);
      expect(formatted).toMatch(/\d{4}/);
    });
  });

  // The caller's live clock (see useNowTick); only an active run's chip reads
  // it, so the settled cases pass an arbitrary value.
  const NOW = 10_000;

  it('shows total time for a completed run with valid timestamps', () => {
    const run = makeRun({
      status: 'completed',
      created_at: 1000,
      completed_at: 1000 + 3600,
    });
    expect(formatHomeRunTimeChip(run, NOW)).toBe('Total time: 1 hour');
  });

  it('reports a sub-minute real span as "< 1 minute" for a completed run', () => {
    const run = makeRun({
      status: 'completed',
      created_at: 1000,
      updated_at: 1000,
      completed_at: null,
    });
    // Real span is zero (updated_at == created_at), not a fabricated 60s.
    expect(formatHomeRunTimeChip(run, NOW)).toBe('Total time: < 1 minute');
  });

  it('shows elapsed time under a minute for a freshly started active run', () => {
    const run = makeRun({
      status: 'running',
      created_at: NOW,
      updated_at: NOW,
      completed_at: null,
    });
    expect(formatHomeRunTimeChip(run, NOW)).toBe('Time elapsed: < 1 minute');
  });

  it('measures an active run’s elapsed time against the live clock', () => {
    // updated_at is 5 minutes behind the clock: it is the last server write,
    // so reading it would freeze the chip between history refreshes.
    const run = makeRun({
      status: 'synthesizing',
      created_at: NOW - 300,
      updated_at: NOW - 300,
      completed_at: null,
    });
    expect(formatHomeRunTimeChip(run, NOW)).toBe('Time elapsed: 5 minutes');
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

  // The exact task types the engine provider mints, as observed in the durable
  // task table of real runs. Every one must land on a phase (or be a deliberate
  // null), so an unmapped task type cannot silently strand the flow.
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
    // A run reporting stage events (`latest_stage`) rather than a leased
    // durable task has that as its only progress signal.
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

  // Every stage event type paired with the durable task type that reports the
  // same underlying node, so the two progress signals can be checked for
  // agreement through the public API rather than by reaching into TASK_PHASE
  // and STAGE_PHASE directly. `supervisor.plan` is the one stage type whose
  // task counterpart is not name-for-name identical (`engine.node.supervisor`,
  // per `_canonical_event_type` in app/engine_adapter/events.py); every other
  // pair differs only by the `engine.node.` prefix.
  const STAGE_TASK_PAIRS: [string, string][] = [
    ['supervisor.plan', 'engine.node.supervisor'],
    ['literature_review', 'engine.node.literature_review'],
    ['generate', 'engine.node.generate'],
    ['reflection', 'engine.node.reflection'],
    ['proximity', 'engine.node.proximity'],
    ['ranking', 'engine.node.ranking'],
    ['evolve', 'engine.node.evolve'],
    ['meta_review', 'engine.node.meta_review'],
    ['deep_verification', 'engine.node.deep_verification'],
    ['research_overview', 'engine.node.research_overview'],
  ];

  it('reports the same phase for a stage event as for its durable-task counterpart', () => {
    // TASK_PHASE and STAGE_PHASE are two tables for the same four-step flow;
    // if they drift, a run reports a different step depending on which
    // progress signal happens to be present rather than what work it is
    // actually doing. This is what let deep_verification read phase 3 from a
    // leased task and phase 4 from a stage event: each mapping's own pinned
    // cases (above, and in ENGINE_TASK_PHASES) matched its own hand-written
    // expectation and neither test caught the two disagreeing.
    for (const [stage, task] of STAGE_TASK_PAIRS) {
      const stagePhase = homeRunStepIndex(
        makeRun({status: 'running', latest_stage: stage}),
      );
      const taskPhase = homeRunStepIndex(makeRun(activeTask(task)));
      expect(stagePhase, `stage '${stage}' vs task '${task}'`).toBe(taskPhase);
    }
  });

  it('reports no phase for a running run that reports no progress yet', () => {
    // Neither signal is present: the caller holds the last phase rather than
    // the flow claiming to be back at the first step.
    expect(
      homeRunStepIndex(makeRun({status: 'running', latest_stage: null})),
    ).toBeNull();
    expect(homeRunStepIndex(makeRun(activeTask(null)))).toBeNull();
    expect(homeRunStepIndex(makeRun(activeTask('engine.node.unknown')))).toBe(
      null,
    );
  });

  it('re-enters an earlier phase when the run cycles back to it', () => {
    // The engine loops, so a later cycle genuinely returns to generation;
    // the flow reports where the run actually is, not its furthest point.
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
      // The last server write, deliberately stale: an executing run's elapsed
      // chip must not be pinned to it.
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

    // 30s + 60s = 90s, which rounds to two minutes. No refetch happens here:
    // the chip has to move on its own clock.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText('Time elapsed: 2 minutes')).toBeInTheDocument();
  });
});

describe('home recents run steps', () => {
  // A running engine run leased on `active_task`: the only live progress signal
  // that provider reports (it emits no stage events).
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

  function labels(selector: string): (string | null | undefined)[] {
    return [...document.querySelectorAll('.reference-run-step')]
      .filter(step => step.querySelector(selector))
      .map(
        step => step.querySelector('.reference-run-step-label')?.textContent,
      );
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

  it('marks no phase done or current: the list itself is the signal', () => {
    render(<RunStepFlow run={runOn('engine.fanout.reflection.item')} />);
    expect(labels('.reference-run-step-done')).toEqual([]);
  });

  it('carries one spinner, on the In Progress row', () => {
    render(<RunStepFlow run={runOn('engine.fanout.reflection.item')} />);
    expect(
      document.querySelectorAll('.reference-run-step-spinner'),
    ).toHaveLength(1);
    // It stands in for a glyph rather than sitting beside one.
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

    // The engine loops, so it genuinely re-enters reviewing — and proximity
    // runs after the tournament. The flow reports the phase the run is in,
    // rather than retaining the furthest one: hiding that backward step was
    // the defect, since it presented a regression as forward progress.
    rerender(<RunStepFlow run={runOn('engine.fanout.review.item')} />);
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
      'Reviewing hypotheses',
    ]);
  });

  it('keeps the final phase while proximity runs after the tournament', () => {
    const {rerender} = render(
      <RunStepFlow run={runOn('engine.ranking.match')} />,
    );
    expect(shownPhases()).toHaveLength(4);

    // Proximity executes after the tournament and maps to the same final
    // display phase, so the flow holds all four steps rather than stepping
    // back to reviewing.
    rerender(<RunStepFlow run={runOn('engine.node.proximity')} />);
    expect(shownPhases()).toHaveLength(4);
  });

  it('holds the revealed phases while the run reports none', () => {
    const {rerender} = render(
      <RunStepFlow run={runOn('engine.node.generate')} />,
    );
    // Routing between agents reports no phase of its own.
    rerender(<RunStepFlow run={runOn('engine.node.orchestrator')} />);
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
    ]);
  });
});

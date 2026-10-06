import {describe, expect, it, afterEach, vi} from 'vitest';
import type {Run} from '@/api/runs';
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

  it('derives the phase from the engine provider’s active durable task', () => {
    for (const [task, phase] of ENGINE_TASK_PHASES) {
      expect(homeRunStepIndex(makeRun(activeTask(task))), task).toBe(phase);
    }
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
});

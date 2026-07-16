import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import type {Run} from '@/api/runs';
import {RunStepFlow} from './home_recents_run_steps';

// A running engine run leased on `active_task`: the only live progress signal
// that provider reports (it emits no stage events).
function runOn(active_task: string): Run {
  return {
    id: 'r1',
    research_goal: 'goal',
    profile: 'standard',
    status: 'running',
    provider: 'engine',
    config: {},
    created_at: 0,
    updated_at: 0,
    completed_at: null,
    error: null,
    latest_stage: null,
    execution_progress: {
      determinate: false,
      completed_tasks: 1,
      total_tasks: 2,
      fraction: null,
      active_task,
      queued_tasks: 1,
    },
  } as Run;
}

function labels(selector: string): (string | null | undefined)[] {
  return [...document.querySelectorAll('.reference-run-step')]
    .filter(step => step.querySelector(selector))
    .map(step => step.querySelector('.reference-run-step-label')?.textContent);
}

function shownPhases(): (string | null | undefined)[] {
  return [...document.querySelectorAll('.reference-run-step-icon')].map(
    icon =>
      icon.parentElement?.querySelector('.reference-run-step-label')
        ?.textContent,
  );
}

describe('RunStepFlow', () => {
  it('reveals only the phases the run has actually reached', () => {
    render(<RunStepFlow run={runOn('engine.node.supervisor')} />);
    expect(shownPhases()).toEqual(['Exploring focus areas']);
    expect(screen.getByText('In Progress : 0%')).toBeInTheDocument();
  });

  it('reveals each further phase as the run reaches it', () => {
    const {rerender} = render(
      <RunStepFlow run={runOn('engine.node.generate')} />,
    );
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
    ]);
    expect(screen.getByText('In Progress : 25%')).toBeInTheDocument();

    rerender(<RunStepFlow run={runOn('engine.ranking.match')} />);
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
      'Reviewing hypotheses',
      'Playing tournament',
    ]);
    expect(screen.getByText('In Progress : 75%')).toBeInTheDocument();
  });

  it('checks the phases the run is past, and only those', () => {
    render(<RunStepFlow run={runOn('engine.fanout.reflection.item')} />);
    expect(labels('.reference-run-step-done')).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
    ]);
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

  it('keeps revealed phases when the run cycles back to an earlier one', () => {
    const {rerender} = render(
      <RunStepFlow run={runOn('engine.ranking.match')} />,
    );
    expect(shownPhases()).toHaveLength(4);

    // The engine loops, so it genuinely re-enters reviewing. The tournament
    // row must not vanish, but it is no longer behind the run.
    rerender(<RunStepFlow run={runOn('engine.fanout.review.item')} />);
    expect(shownPhases()).toHaveLength(4);
    expect(labels('.reference-run-step-done')).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
    ]);
    expect(screen.getByText('In Progress : 50%')).toBeInTheDocument();
  });

  it('holds the last phase while the run reports none', () => {
    const {rerender} = render(
      <RunStepFlow run={runOn('engine.node.generate')} />,
    );
    expect(screen.getByText('In Progress : 25%')).toBeInTheDocument();

    // Routing between agents reports no phase of its own.
    rerender(<RunStepFlow run={runOn('engine.node.orchestrator')} />);
    expect(screen.getByText('In Progress : 25%')).toBeInTheDocument();
    expect(shownPhases()).toEqual([
      'Exploring focus areas',
      'Generating hypotheses',
    ]);
  });
});

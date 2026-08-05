import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import type {Run} from '@/api/runs';
import {makeRun} from '@/test_fixtures';
import {RunStepFlow} from './home_recents_run_steps';

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
    .map(step => step.querySelector('.reference-run-step-label')?.textContent);
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
  expect(document.querySelectorAll('.reference-run-step-spinner')).toHaveLength(
    1,
  );
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

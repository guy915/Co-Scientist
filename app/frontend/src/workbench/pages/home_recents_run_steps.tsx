import {Fragment, useEffect, useState} from 'react';
import {type Run} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {homeRunStepIndex} from './home_recents_data';

// The four phases of a live run, each with the glyph it shows in the flow.
// A run's real unit of work is mapped onto one of these by homeRunStepIndex.
const RUN_STEPS: {icon: IconName; label: string}[] = [
  {icon: 'summarize', label: 'Exploring focus areas'},
  {icon: 'rate_review', label: 'Generating hypotheses'},
  {icon: 'reviews', label: 'Reviewing hypotheses'},
  {icon: 'chess', label: 'Playing tournament'},
];

/**
 * Renders the live flow for an active run: an "In Progress" row carrying the
 * spinner, then the phases up to the one the run is currently in.
 *
 * The phase comes from the run's own reported progress, so the flow tracks
 * real work rather than a timer. It shows the *latest* reported phase, not
 * the furthest one ever reached: a run genuinely returns to earlier phases
 * (every new work cycle re-enters generation/review, and proximity follows
 * the tournament), and retaining the furthest phase masked those backward
 * steps instead of reporting them. Rows appearing and disappearing as the
 * phase moves is the honest signal.
 *
 * @param run The active run to show progress for.
 */
export function RunStepFlow({run}: {run: Run}) {
  const phase = homeRunStepIndex(run);
  // A run reports no phase while routing between agents and in the gaps
  // between leased tasks. Hold the last phase actually observed so those gaps
  // read as the work continuing, rather than snapping back to the first step.
  // A *reported* phase replaces it outright — see the docstring for why the
  // flow no longer retains the furthest phase seen.
  const [currentPhase, setCurrentPhase] = useState(phase ?? 1);
  useEffect(() => {
    if (phase === null) return;
    setCurrentPhase(phase);
  }, [phase]);
  const revealed = RUN_STEPS.slice(0, currentPhase);

  return (
    <div className="reference-run-steps">
      <div className="reference-run-step-list">
        <div className="reference-run-step">
          <span
            aria-hidden="true"
            className="reference-run-step-spinner reference-run-step-glyph"
          />
          <span className="reference-run-step-label">In Progress</span>
        </div>
        <div aria-hidden="true" className="reference-run-step-delimiter" />
        {revealed.map((step, index) => (
          <Fragment key={step.label}>
            <RunStepItem icon={step.icon} label={step.label} />
            {index < revealed.length - 1 && (
              <div
                aria-hidden="true"
                className="reference-run-step-delimiter"
              />
            )}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

// One phase's glyph and label. A row's presence is the whole signal: the flow
// only lists phases the run has entered, and its single spinner lives in the
// In Progress row. There is deliberately no per-row done/current marker (the
// .reference-run-step-done check style is kept for a future one).
function RunStepItem({icon, label}: {icon: IconName; label: string}) {
  return (
    <div className="reference-run-step">
      <Icon
        aria-hidden="true"
        className="reference-run-step-icon"
        name={icon}
      />
      <span className="reference-run-step-label">{label}</span>
    </div>
  );
}

// The active-task label: the humanized durable-task-lease signal
// (`execution_progress.active_task`) when one is present, else the
// humanized stage-event signal (`latest_stage`) when that is present
// instead, else a neutral placeholder while neither signal has arrived yet.
function activeTaskLabel(run: Run): string {
  const activeTask = run.execution_progress?.active_task;
  if (activeTask) return humanizeTask(activeTask);
  if (run.latest_stage) return humanizeTask(run.latest_stage);
  return 'Waiting for Supervisor allocation';
}

// Committed-task counts for the "N of M complete" line, only while the
// Supervisor's progress is determinate.
function committedTaskCounts(run: Run): {
  completed: number;
  total: number;
  queued: number;
} | null {
  const progress = run.execution_progress;
  if (!progress?.determinate) return null;
  return {
    completed: progress.completed_tasks,
    total: progress.total_tasks,
    queued: progress.queued_tasks,
  };
}

/**
 * Renders truthful task-queue progress for a live run: what it is working on
 * now, and how much of the Supervisor's committed task budget is done. Both
 * are stated in words -- a bar was removed because its fraction is only known
 * once the budget is committed, so most of a run it read as motion without
 * information.
 */
export function RunExecutionProgress({run}: {run: Run}) {
  const activeTask = activeTaskLabel(run);
  const counts = committedTaskCounts(run);

  return (
    <section className="mt-4" aria-label="Run execution progress">
      <strong className="block text-xs font-medium text-cosci-fg">
        {activeTask}
      </strong>
      {counts ? (
        <p className="mt-2 text-xs text-cosci-muted">
          {counts.completed} of {counts.total} committed tasks complete ·{' '}
          {counts.queued} queued
        </p>
      ) : null}
    </section>
  );
}

function humanizeTask(value: string): string {
  return value
    .replaceAll('.', ' ')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, letter => letter.toUpperCase());
}

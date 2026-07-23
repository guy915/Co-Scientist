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
 * spinner, then the phases the run has reached so far.
 *
 * The phase comes from the run's own reported progress, so the flow tracks
 * real work rather than a timer. The run revisits phases every cycle, so the
 * list reads as a record of the phases it has entered: it grows by the
 * furthest phase reached, never by the current one, so cycling back to an
 * earlier phase cannot make rows it already showed disappear.
 *
 * @param run The active run to show progress for.
 */
export function RunStepFlow({run}: {run: Run}) {
  const phase = homeRunStepIndex(run);
  // A run reports no phase while routing between agents and in the gaps
  // between leased tasks. Hold the last phase actually observed so those gaps
  // read as the work continuing, rather than snapping back to the first step.
  const [furthestPhase, setFurthestPhase] = useState(phase ?? 1);
  useEffect(() => {
    if (phase === null) return;
    setFurthestPhase(seen => Math.max(seen, phase));
  }, [phase]);
  const revealed = RUN_STEPS.slice(0, furthestPhase);

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

/**
 * Renders truthful task-queue progress for a live run. A percentage appears
 * only when the Supervisor has committed a durable task budget; otherwise the
 * bar remains explicitly indeterminate.
 */
// The indeterminate pulse variant, shown while no fraction is known yet.
function IndeterminateProgressBar() {
  return (
    <div
      className="mt-2 h-1.5 overflow-hidden rounded-full bg-cosci-hover"
      role="progressbar"
      aria-label="Scientific task completion"
    >
      <div className="h-full w-1/3 animate-pulse rounded-full bg-cosci-blue-strong" />
    </div>
  );
}

// The determinate width variant, shown once a real fraction is known.
function DeterminateProgressBar({percentage}: {percentage: number}) {
  return (
    <div
      className="mt-2 h-1.5 overflow-hidden rounded-full bg-cosci-hover"
      role="progressbar"
      aria-label="Scientific task completion"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percentage}
    >
      <div
        className="h-full rounded-full bg-cosci-blue-strong transition-[width]"
        style={{width: `${percentage}%`}}
      />
    </div>
  );
}

// The progress bar itself: determinate width when a fraction is known,
// otherwise an indeterminate pulse.
function ProgressBar({percentage}: {percentage: number | null}) {
  return percentage === null ? (
    <IndeterminateProgressBar />
  ) : (
    <DeterminateProgressBar percentage={percentage} />
  );
}

// The active-task label: the humanized durable task when the engine provider
// reports one, else the humanized stage when the mock provider reports one,
// else a neutral placeholder while neither signal has arrived yet.
function activeTaskLabel(run: Run): string {
  const activeTask = run.execution_progress?.active_task;
  if (activeTask) return humanizeTask(activeTask);
  if (run.latest_stage) return humanizeTask(run.latest_stage);
  return 'Waiting for Supervisor allocation';
}

// The completion percentage, only once the Supervisor has committed a real,
// non-zero fraction; null (indeterminate) otherwise.
function executionPercentage(run: Run): number | null {
  const progress = run.execution_progress;
  if (!progress?.determinate || progress.fraction === null) return null;
  return Math.round(progress.fraction * 100);
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

export function RunExecutionProgress({run}: {run: Run}) {
  const activeTask = activeTaskLabel(run);
  const percentage = executionPercentage(run);
  const counts = committedTaskCounts(run);

  return (
    <section className="mt-4" aria-label="Run execution progress">
      <div className="flex items-center justify-between gap-3 text-xs">
        <strong className="font-medium text-cosci-fg">{activeTask}</strong>
        <span className="text-cosci-muted">
          {percentage === null ? 'Progress pending' : `${percentage}%`}
        </span>
      </div>
      <ProgressBar percentage={percentage} />
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

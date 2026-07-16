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
 * Renders the live "session loading" flow for an active run: an "In Progress"
 * chip over the four phases, each with its glyph, a check once passed, and an
 * indeterminate spinner on the phase the run is currently working in.
 *
 * The phase comes from the run's own reported progress, so the flow tracks
 * real work: it advances when the run advances, and re-enters an earlier phase
 * when the run genuinely cycles back to it. The chip stays unnumbered because
 * of that re-entry: the run does not march through the phases once, so a
 * "step N of 4" would both overstate the shape of the work and count backwards.
 *
 * @param run The active run to show progress for.
 */
export function RunStepFlow({run}: {run: Run}) {
  const phase = homeRunStepIndex(run);
  // A run reports no phase while routing between agents and in the gaps
  // between leased tasks. Hold the last phase actually observed so those gaps
  // read as the work continuing, rather than snapping back to the first step.
  const [lastPhase, setLastPhase] = useState(phase ?? 1);
  useEffect(() => {
    if (phase !== null) setLastPhase(phase);
  }, [phase]);
  const activeIndex = phase ?? lastPhase;

  return (
    <div className="reference-run-steps">
      <span className="reference-run-step-chip">
        <span aria-hidden="true" className="reference-run-step-spinner" />
        In Progress
      </span>
      <div className="reference-run-step-list">
        {RUN_STEPS.map((step, index) => {
          const stepNumber = index + 1;
          return (
            <Fragment key={step.label}>
              <RunStepItem
                icon={step.icon}
                label={step.label}
                done={stepNumber < activeIndex}
                active={stepNumber === activeIndex}
              />
              {index < RUN_STEPS.length - 1 && (
                <div
                  aria-hidden="true"
                  className="reference-run-step-delimiter"
                />
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

// One phase's glyph, label, check once passed, and indeterminate spinner while
// it's the phase currently in progress.
function RunStepItem({
  icon,
  label,
  done,
  active,
}: {
  icon: IconName;
  label: string;
  done: boolean;
  active: boolean;
}) {
  return (
    <div className="reference-run-step">
      <Icon
        aria-hidden="true"
        className="reference-run-step-icon"
        name={icon}
      />
      <span className="reference-run-step-label">{label}</span>
      {done && (
        <Icon
          aria-hidden="true"
          className="reference-run-step-done"
          name="check"
        />
      )}
      {active && (
        <span aria-hidden="true" className="reference-run-step-spinner" />
      )}
    </div>
  );
}

/**
 * Renders truthful task-queue progress for a live run. A percentage appears
 * only when the Supervisor has committed a durable task budget; otherwise the
 * bar remains explicitly indeterminate.
 */
export function RunExecutionProgress({run}: {run: Run}) {
  const progress = run.execution_progress;
  const activeTask = progress?.active_task
    ? humanizeTask(progress.active_task)
    : run.latest_stage
      ? humanizeTask(run.latest_stage)
      : 'Waiting for Supervisor allocation';
  const percentage =
    progress?.determinate && progress.fraction !== null
      ? Math.round(progress.fraction * 100)
      : null;

  return (
    <section className="mt-4" aria-label="Run execution progress">
      <div className="flex items-center justify-between gap-3 text-xs">
        <strong className="font-medium text-cosci-fg">{activeTask}</strong>
        <span className="text-cosci-muted">
          {percentage === null ? 'Progress pending' : `${percentage}%`}
        </span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-cosci-hover"
        role="progressbar"
        aria-label="Scientific task completion"
        aria-valuemin={percentage === null ? undefined : 0}
        aria-valuemax={percentage === null ? undefined : 100}
        aria-valuenow={percentage ?? undefined}
      >
        <div
          className={
            percentage === null
              ? 'h-full w-1/3 animate-pulse rounded-full bg-cosci-blue-strong'
              : 'h-full rounded-full bg-cosci-blue-strong transition-[width]'
          }
          style={percentage === null ? undefined : {width: `${percentage}%`}}
        />
      </div>
      {progress?.determinate ? (
        <p className="mt-2 text-xs text-cosci-muted">
          {progress.completed_tasks} of {progress.total_tasks} committed tasks
          complete · {progress.queued_tasks} queued
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

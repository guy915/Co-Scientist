import {type Run} from '@/api/runs';

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

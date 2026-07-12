import {isActiveStatus, type Run} from '@/api/runs';
import {formatDurationPhrase} from '@/lib/duration';

// Formats a run's creation date for the meta chip, e.g. "July 8, 2026".
// Timestamps on Run are Unix seconds, hence the *1000 to build a Date.
const HOME_RUN_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: 'long',
  day: 'numeric',
  year: 'numeric',
});

/**
 * Formats a run's creation date for the recents-card meta chip, e.g.
 * "July 8, 2026".
 *
 * @param timestamp The run's creation time in Unix seconds.
 * @returns The localized long-form date string.
 */
export function formatHomeRunDate(timestamp: number): string {
  return HOME_RUN_DATE_FMT.format(new Date(timestamp * 1000));
}

// Real wall-clock duration phrase from the run's persisted start/end
// timestamps, or null when no usable end timestamp is recorded. A sub-minute
// real span renders as "< 1 minute" rather than being rounded up.
function completedDurationLabel(run: Run): string | null {
  const endTime = run.completed_at ?? run.updated_at;
  if (!endTime) return null;
  const seconds = endTime - run.created_at;
  if (seconds < 0) return null;
  if (seconds < 60) return '< 1 minute';
  return formatDurationPhrase(seconds);
}

// Total wall-clock duration for a finished (or presumed-finished) run, driven
// by the run's real timestamps: the measured span when available, "In
// progress" for active runs, and the raw status otherwise.
function formatHomeRunDuration(run: Run): string {
  const completed = completedDurationLabel(run);
  if (completed !== null) return completed;
  if (isActiveStatus(run.status)) return 'In progress';
  return formatHomeRunStatus(run);
}

// Elapsed time since an active run was created, floored at zero to guard
// against clock skew between client and server timestamps.
function formatHomeRunElapsed(run: Run): string {
  const elapsedSeconds = Math.max(
    0,
    (run.updated_at || Date.now() / 1000) - run.created_at,
  );
  if (elapsedSeconds < 60) return '< 1 minute';
  return formatDurationPhrase(elapsedSeconds);
}

/**
 * Builds the second meta chip on a recent-run card: total time once
 * completed, live elapsed time while active, or the raw status label
 * otherwise.
 *
 * @param run The run to describe.
 * @returns The chip text.
 */
export function formatHomeRunTimeChip(run: Run): string {
  if (run.status === 'completed') {
    return `Total time: ${formatHomeRunDuration(run)}`;
  }
  if (isActiveStatus(run.status)) {
    return `Time elapsed: ${formatHomeRunElapsed(run)}`;
  }
  return `Status: ${formatHomeRunStatus(run)}`;
}

function formatHomeRunStatus(run: Run): string {
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

/**
 * Looks up a completed run's top score, distinguishing "no entry yet" (score
 * still loading) from "known to be null" via hasOwnProperty rather than a
 * plain index lookup, since both cases would otherwise read as undefined.
 *
 * @param run The run whose score to resolve.
 * @param scoresByRunId Top Elo score per run id.
 * @returns The top score, or null if unknown/not completed.
 */
export function homeRunScore(
  run: Run,
  scoresByRunId: Record<string, number | null>,
): number | null {
  if (run.status !== 'completed') return null;
  return Object.prototype.hasOwnProperty.call(scoresByRunId, run.id)
    ? scoresByRunId[run.id]
    : null;
}

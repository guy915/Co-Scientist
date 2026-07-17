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
// timestamps, or null when no usable end timestamp is recorded. Sub-minute
// spans render as "< 1 minute" rather than being rounded up.
function completedDurationLabel(run: Run): string | null {
  const endTime = run.completed_at ?? run.updated_at;
  if (!endTime) return null;
  const seconds = endTime - run.created_at;
  if (seconds < 0) return null;
  return formatDurationPhrase(seconds, {subMinute: true});
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
  return formatDurationPhrase(elapsedSeconds, {subMinute: true});
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

// Phase of the four-step home flow each unit of work belongs to: 1 Exploring
// focus areas, 2 Generating hypotheses, 3 Reviewing hypotheses, 4 Playing
// tournament. `null` means "carries no phase signal" (see homeRunStepIndex).
//
// Keyed by the distinguishing segment of a durable task type, which the engine
// provider mints in `app/engine_tasks.py` as `engine.node.<graph node>`,
// `engine.fanout.<workflow>.<step>`, `engine.ranking.<step>`, or a bare
// `engine.<step>`. Keying on that segment rather than the whole string means
// one entry covers a node and its fan-out siblings alike (`engine.node.ranking`
// and `engine.ranking.match` both land on the tournament).
const TASK_PHASE: Record<string, number | null> = {
  bootstrap: 1,
  supervisor: 1,
  // Per-cycle routing between agents, not a phase of its own: reporting it
  // would bounce the flow back to Exploring at every cycle boundary.
  orchestrator: null,
  generate: 2,
  generation: 2,
  // The Generation agent owns literature review (engine `NODE_TO_AGENT`).
  literature_review: 2,
  reflection: 3,
  comprehensive_reflection: 3,
  review: 3,
  verification: 3,
  deep_verification: 3,
  safety_screen: 3,
  proximity: 3,
  ranking: 4,
  evolve: 4,
  meta_review: 4,
  research_overview: 4,
  finalize: 4,
};

// Pipeline-stage event type -> phase, mirroring TASK_PHASE for the mock
// provider, which reports progress as `_STAGE_EVENT_TYPES` events (see
// app/store/runs.py) rather than durable tasks.
const STAGE_PHASE: Record<string, number> = {
  'supervisor.plan': 1,
  literature_review: 2,
  generate: 2,
  reflection: 3,
  proximity: 3,
  ranking: 4,
  evolve: 4,
  meta_review: 4,
  deep_verification: 4,
  research_overview: 4,
};

// The segment of a durable task type that identifies the work being done:
// the graph node for `engine.node.<key>`, the workflow for
// `engine.fanout.<workflow>.<step>`, and the leading step otherwise.
function taskPhaseKey(taskType: string): string {
  const [, first = '', second = ''] = taskType.split('.');
  return first === 'node' || first === 'fanout' ? second : first;
}

/**
 * Derives the 1-based phase (1-4) a live run is currently working in, reading
 * whichever real progress signal its provider reports: the engine provider
 * leases durable tasks (`execution_progress.active_task`) and emits no stage
 * events, while the mock provider emits stage events (`latest_stage`) and
 * leases no tasks. Each signal is absent for the other provider, so both are
 * consulted rather than either being assumed.
 *
 * The engine revisits phases on every cycle, so this deliberately moves
 * backwards when the run genuinely returns to generating or reviewing.
 *
 * @param run The active run.
 * @returns The phase in the range 1-4, or null when the run reports no phase
 *   signal right now (between leased tasks, or while routing), which leaves
 *   the caller showing the last phase actually observed.
 */
export function homeRunStepIndex(run: Run): number | null {
  if (run.status === 'queued') return 1;
  if (run.status === 'synthesizing') return 4;
  // An unmapped task type and a deliberately phase-less one (orchestrator)
  // both mean "no signal", so both normalize to null.
  const activeTask = run.execution_progress?.active_task;
  const taskPhase = activeTask
    ? (TASK_PHASE[taskPhaseKey(activeTask)] ?? null)
    : null;
  if (taskPhase !== null) return taskPhase;
  const stage = run.latest_stage;
  return (stage ? STAGE_PHASE[stage] : null) ?? null;
}

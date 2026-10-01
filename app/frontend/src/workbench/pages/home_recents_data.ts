import {isActiveStatus, isCompletedStatus, type Run} from '@/api/runs';
import {formatDurationPhrase} from '@/lib/duration';
import {capitalizeTerm} from '@/lib/text';

// Formats a run's creation date for the meta chip, e.g. "Jul 8, 2026".
// Timestamps on Run are Unix seconds, hence the *1000 to build a Date.
//
// Abbreviated month, not the full name: the meta row is two chips side by
// side in a 19rem column, which leaves ~232px of text budget, and a long
// month spent enough of it that a routine pair ("August 7, 2026" +
// "Time elapsed: 3 minutes", 235.6px measured) wrapped the second chip onto
// its own line while the card still looked half empty.
const HOME_RUN_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

/**
 * Formats a run's creation date for the recents-card meta chip, e.g.
 * "Jul 8, 2026".
 *
 * @param timestamp The run's creation time in Unix seconds.
 * @returns The localized short-form date string.
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

// Total wall-clock duration for a finished run, driven by the run's real
// timestamps: the measured span when available, else the raw status label.
function formatHomeRunDuration(run: Run): string {
  return completedDurationLabel(run) ?? formatHomeRunStatus(run);
}

// Elapsed time since an active run was created, floored at zero to guard
// against clock skew between client and server timestamps. Measured against
// the caller's live clock rather than `updated_at`: that is the last server
// write, so an executing run's chip sat frozen between history refreshes.
function formatHomeRunElapsed(run: Run, nowSeconds: number): string {
  const elapsedSeconds = Math.max(0, nowSeconds - run.created_at);
  return formatDurationPhrase(elapsedSeconds, {subMinute: true});
}

/**
 * Builds the second meta chip on a recent-run card: total time once
 * completed, live elapsed time while active, or the raw status label
 * otherwise.
 *
 * @param run The run to describe.
 * @param nowSeconds The caller's current time in Unix seconds, which an
 *   active run's elapsed time is measured against (see useNowTick) so the
 *   chip keeps advancing between history refreshes.
 * @returns The chip text.
 */
export function formatHomeRunTimeChip(run: Run, nowSeconds: number): string {
  if (isCompletedStatus(run.status)) {
    return `Total time: ${formatHomeRunDuration(run)}`;
  }
  if (isActiveStatus(run.status)) {
    return `Time elapsed: ${formatHomeRunElapsed(run, nowSeconds)}`;
  }
  return `Status: ${formatHomeRunStatus(run)}`;
}

function formatHomeRunStatus(run: Run): string {
  return capitalizeTerm(run.status);
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
  if (!isCompletedStatus(run.status)) return null;
  return Object.prototype.hasOwnProperty.call(scoresByRunId, run.id)
    ? scoresByRunId[run.id]
    : null;
}

// Phase of the four-step home flow each unit of work belongs to: 1 Exploring
// focus areas, 2 Generating hypotheses, 3 Reviewing hypotheses, 4 Playing
// tournament. `null` means "carries no phase signal" (see homeRunStepIndex).
//
// Keyed by the distinguishing segment of a durable task type, which the engine
// provider mints in `app/engine_tasks/__init__.py` as `engine.node.<graph node>`,
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
  ranking: 4,
  // Proximity executes after the tournament, so it belongs to the final
  // display phase even though it is not itself tournament work -- phase 4
  // is "the tournament and everything after", and reporting it as phase 3
  // made the flow step backward right after the tournament.
  proximity: 4,
  evolve: 4,
  meta_review: 4,
  research_overview: 4,
  finalize: 4,
};

// Stage event types the engine appends directly to `run_events`
// (`_STAGE_EVENT_TYPES` in app/store/runs_views.py) -- a narrower, flatter
// vocabulary than TASK_PHASE's durable task types: no bootstrap/orchestrator/
// finalize scaffolding, and no separate entry for a fanned-out node's
// per-item task type (e.g. deep_verification's fan-out reports task phase
// through the `verification` key, but only ever the `deep_verification`
// stage type).
const STAGE_EVENT_TYPES = [
  'supervisor.plan',
  'literature_review',
  'generate',
  'reflection',
  'proximity',
  'ranking',
  'evolve',
  'meta_review',
  'deep_verification',
  'research_overview',
] as const;

// The one stage type `_canonical_event_type` (app/engine_adapter/events.py)
// renames away from its node name: the supervisor node's stage event type is
// `supervisor.plan`, not `supervisor`. Every other stage type above equals
// its TASK_PHASE key directly, so this is the map's only entry.
const STAGE_TYPE_TASK_KEY: Record<string, string> = {
  'supervisor.plan': 'supervisor',
};

// Looks up the phase TASK_PHASE assigns the node behind a stage type, rather
// than restating the number. Throws instead of defaulting a miss to null:
// every stage type today resolves (pinned by the stage/task agreement test
// in home_recents_data.test.ts), so hitting this means a new stage type was
// added upstream with no TASK_PHASE counterpart to derive from -- a real
// decision to make, not a silent null.
function phaseForStageType(stageType: string): number {
  const taskKey = STAGE_TYPE_TASK_KEY[stageType] ?? stageType;
  const phase = TASK_PHASE[taskKey] ?? null;
  if (phase === null) {
    throw new Error(
      `STAGE_PHASE: no TASK_PHASE['${taskKey}'] for stage type '${stageType}'`,
    );
  }
  return phase;
}

// Pipeline-stage event type -> phase, derived from TASK_PHASE so the two
// progress signals cannot drift the way they did when a hand-copied
// `deep_verification` sat at phase 4 here and phase 3 in TASK_PHASE.
const STAGE_PHASE = Object.fromEntries(
  STAGE_EVENT_TYPES.map(stageType => [stageType, phaseForStageType(stageType)]),
) as Record<string, number>;

// The segment of a durable task type that identifies the work being done:
// the graph node for `engine.node.<key>`, the workflow for
// `engine.fanout.<workflow>.<step>`, and the leading step otherwise.
function taskPhaseKey(taskType: string): string {
  const [, first = '', second = ''] = taskType.split('.');
  return first === 'node' || first === 'fanout' ? second : first;
}

// A status that alone determines the phase, bypassing the task/stage signals
// entirely: queued runs have not reached any phase yet, and synthesizing runs
// have finished every phase but 'completed' hasn't landed.
function statusPhaseOverride(status: Run['status']): number | null {
  if (status === 'queued') return 1;
  if (status === 'synthesizing') return 4;
  return null;
}

// This run's durable-task-lease signal: the phase of the task currently
// leased, or null when there is none or its type is unmapped. An unmapped
// task type and a deliberately phase-less one (orchestrator) both mean "no
// signal", so both normalize to null.
function taskPhaseFor(run: Run): number | null {
  const activeTask = run.execution_progress?.active_task;
  if (!activeTask) return null;
  return TASK_PHASE[taskPhaseKey(activeTask)] ?? null;
}

// This run's stage-event signal: the phase of its most recent reported
// `_STAGE_EVENT_TYPES` event, or null when there is none or it maps to no
// phase.
function stagePhaseFor(run: Run): number | null {
  const stage = run.latest_stage;
  if (!stage) return null;
  return STAGE_PHASE[stage] ?? null;
}

/**
 * Derives the 1-based phase (1-4) a live run is currently working in, reading
 * whichever real progress signal is present: a leased durable task
 * (`execution_progress.active_task`) or a reported pipeline-stage event
 * (`latest_stage`). A run carries at most one of the two, so both are
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
  const override = statusPhaseOverride(run.status);
  if (override !== null) return override;
  const taskPhase = taskPhaseFor(run);
  if (taskPhase !== null) return taskPhase;
  return stagePhaseFor(run);
}

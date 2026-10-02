// What a run's `status` means -- the one place that decides it.
//
// The backend reports nine statuses, but the questions the UI asks of them
// do not follow the nine one-to-one: a progress indicator, a stop button, a
// start retry and an end-state page each draw a different line through the
// same list. Every status therefore belongs to one phase (a closed table, so
// a new `RunStatus` does not compile until it is classified), and every
// question is a set of phases. Consumers ask a question by name instead of
// comparing against status strings.
//
// The asymmetries are deliberate and consumers rely on them:
// - `paused` is started and stoppable but not active: it is an unfinished
//   run the scientist may want rid of, yet nothing is progressing.
// - `draft` is neither active nor terminal: it has not begun.
// - `failed`/`blocked` are terminal but never "started", and they keep a
//   start intent so a retry resolves to the same run's outcome instead of
//   creating a second one; `cancelled` retires the intent.
//
// Re-exported through '@/api/runs', which is where callers import it from.

import type {RunStatus} from './run_types';

/** The phases a recognised `RunStatus` can be in. */
type KnownPhase =
  | 'draft'
  | 'active'
  | 'paused'
  | 'completed'
  | 'failure'
  | 'cancelled';

/**
 * A run's place in its lifecycle. `failure` covers both `failed` and
 * `blocked`; `unknown` is a status that has not loaded yet or that this
 * build does not recognise (a newer backend), and answers no to every
 * question.
 */
export type RunPhase = KnownPhase | 'unknown';

const PHASE_OF_STATUS = {
  draft: 'draft',
  queued: 'active',
  running: 'active',
  synthesizing: 'active',
  paused: 'paused',
  completed: 'completed',
  failed: 'failure',
  blocked: 'failure',
  cancelled: 'cancelled',
} as const satisfies Record<RunStatus, KnownPhase>;

// Each question and the phases that answer yes to it.
const PHASES_WHERE = {
  // The workflow is progressing: drives live progress and history polling.
  active: ['active'],
  // Settled for good; will run no further tasks.
  terminal: ['completed', 'failure', 'cancelled'],
  // The server took the start request: the run is running, paused, or done.
  started: ['active', 'paused', 'completed'],
  // The server would accept a cancel.
  stoppable: ['active', 'paused'],
  // Ended without producing a goal report.
  endedWithoutReport: ['failure', 'cancelled'],
  // The create receipt that guards a start retry is spent.
  retiresStartIntent: ['active', 'paused', 'completed', 'cancelled'],
  draft: ['draft'],
  completed: ['completed'],
  cancelled: ['cancelled'],
  failure: ['failure'],
} as const satisfies Record<string, readonly KnownPhase[]>;

type Question = keyof typeof PHASES_WHERE;

// The statuses whose phase is in `P`, derived from the table above so the
// type guards below cannot disagree with the answers they narrow.
type StatusIn<P extends KnownPhase> = {
  [S in RunStatus]: (typeof PHASE_OF_STATUS)[S] extends P ? S : never;
}[RunStatus];
type StatusWhere<Q extends Question> = StatusIn<
  (typeof PHASES_WHERE)[Q][number]
>;

/** Terminal run statuses that ended without a completed goal report. */
export type TerminalNonCompletedStatus = StatusWhere<'endedWithoutReport'>;

type StatusInput = string | null | undefined;

/**
 * Classifies a run status into its lifecycle phase.
 *
 * @param status The run status (undefined before load, or any string a
 *   newer backend may send).
 * @returns The phase, or `unknown` when the status is absent or unrecognised.
 */
export function runLifecycle(status: StatusInput): RunPhase {
  if (!status || !Object.hasOwn(PHASE_OF_STATUS, status)) return 'unknown';
  return PHASE_OF_STATUS[status as RunStatus];
}

function holds(question: Question, status: StatusInput): boolean {
  const phases: readonly RunPhase[] = PHASES_WHERE[question];
  return phases.includes(runLifecycle(status));
}

/** Whether a run's workflow is still in progress. `paused` is not. */
export function isActiveStatus(
  status: StatusInput,
): status is StatusWhere<'active'> {
  return holds('active', status);
}

/**
 * Whether a run has reached a terminal state.
 *
 * Distinct from `!isActiveStatus`: a `draft` run is neither active nor
 * terminal -- it has not started, so new documents it is given will still be
 * indexed once it runs.
 */
export function isTerminalStatus(
  status: StatusInput,
): status is StatusWhere<'terminal'> {
  return holds('terminal', status);
}

/**
 * Whether the server has taken a run's start request: it is running, paused,
 * or completed. `failed`/`blocked` are not started -- a start that ended in
 * either is reported as an error, not as an already-started run.
 */
export function isStartedStatus(
  status: StatusInput,
): status is StatusWhere<'started'> {
  return holds('started', status);
}

/**
 * Whether a run can still be stopped: anything the server would accept a
 * cancel for. Unlike `isActiveStatus` this includes `paused`, which is
 * precisely an unfinished run the scientist may want rid of; a draft has
 * not started, so there is nothing to stop.
 */
export function isStoppableStatus(
  status: StatusInput,
): status is StatusWhere<'stoppable'> {
  return holds('stoppable', status);
}

/**
 * Whether a run is terminal but not `completed`: it ended without producing
 * a goal report (failed, cancelled, or blocked).
 */
export function isTerminalNonCompletedStatus(
  status: StatusInput,
): status is TerminalNonCompletedStatus {
  return holds('endedWithoutReport', status);
}

/**
 * Whether a run's pending create intent is spent: the run was started or
 * cancelled. A draft keeps it (still to be started), and so do `failed` and
 * `blocked`, so retrying Start resolves to that run's outcome rather than
 * creating a duplicate.
 */
export function retiresStartIntent(
  status: StatusInput,
): status is StatusWhere<'retiresStartIntent'> {
  return holds('retiresStartIntent', status);
}

/** Whether a run ended on its own without a report: `failed` or `blocked`. */
export function isFailureStatus(
  status: StatusInput,
): status is StatusWhere<'failure'> {
  return holds('failure', status);
}

/** Whether a run is still a draft, awaiting its start. */
export function isDraftStatus(
  status: StatusInput,
): status is StatusWhere<'draft'> {
  return holds('draft', status);
}

/** Whether a run finished and produced its goal report. */
export function isCompletedStatus(
  status: StatusInput,
): status is StatusWhere<'completed'> {
  return holds('completed', status);
}

/** Whether a run was cancelled. */
export function isCancelledStatus(
  status: StatusInput,
): status is StatusWhere<'cancelled'> {
  return holds('cancelled', status);
}

/**
 * Whether a run is executing. `unknown` is a real third state: until a
 * status exists, neither the results chrome nor the live view is the right
 * guess.
 */
export type RunActivity = 'active' | 'inactive' | 'unknown';

/**
 * A run's activity for choosing between its live view and its results.
 *
 * @param status The run status (undefined before load).
 * @returns `unknown` with no status, else `active` only while in progress.
 */
export function runActivity(status: StatusInput): RunActivity {
  if (!status) return 'unknown';
  return isActiveStatus(status) ? 'active' : 'inactive';
}

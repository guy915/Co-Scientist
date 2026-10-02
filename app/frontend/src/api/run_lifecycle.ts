import type {RunStatus} from './run_types';

type StatusInput = string | null | undefined;
type ActiveStatus = Extract<RunStatus, 'queued' | 'running' | 'synthesizing'>;
type FailureStatus = Extract<RunStatus, 'failed' | 'blocked'>;
export type TerminalNonCompletedStatus = FailureStatus | 'cancelled';

/** Paused runs have started, but their workflow is not progressing. */
export function isActiveStatus(status: StatusInput): status is ActiveStatus {
  return (
    status === 'queued' || status === 'running' || status === 'synthesizing'
  );
}

export function isFailureStatus(status: StatusInput): status is FailureStatus {
  return status === 'failed' || status === 'blocked';
}

export function isDraftStatus(status: StatusInput): status is 'draft' {
  return status === 'draft';
}

export function isCompletedStatus(status: StatusInput): status is 'completed' {
  return status === 'completed';
}

export function isCancelledStatus(status: StatusInput): status is 'cancelled' {
  return status === 'cancelled';
}

/** Terminal runs without a report keep a distinct end-state view. */
export function isTerminalNonCompletedStatus(
  status: StatusInput,
): status is TerminalNonCompletedStatus {
  return isFailureStatus(status) || isCancelledStatus(status);
}

/** Draft and paused runs are neither active nor terminal. */
export function isTerminalStatus(
  status: StatusInput,
): status is TerminalNonCompletedStatus | 'completed' {
  return isTerminalNonCompletedStatus(status) || isCompletedStatus(status);
}

export function isStoppableStatus(
  status: StatusInput,
): status is ActiveStatus | 'paused' {
  return isActiveStatus(status) || status === 'paused';
}

/** Failed/blocked starts remain errors even though the run is terminal. */
export function isStartedStatus(
  status: StatusInput,
): status is ActiveStatus | 'paused' | 'completed' {
  return isStoppableStatus(status) || isCompletedStatus(status);
}

/** Failed/blocked runs retain their receipt so Start retries don't duplicate. */
export function retiresStartIntent(
  status: StatusInput,
): status is ActiveStatus | 'paused' | 'completed' | 'cancelled' {
  return isStartedStatus(status) || isCancelledStatus(status);
}

export type RunActivity = 'active' | 'inactive' | 'unknown';

/** Wait for a status before choosing between the live view and results. */
export function runActivity(status: StatusInput): RunActivity {
  if (!status) return 'unknown';
  return isActiveStatus(status) ? 'active' : 'inactive';
}

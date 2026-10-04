import {useEffect, useRef, useState} from 'react';
import {
  cancelRun,
  HttpError,
  isStoppableStatus,
  type RunStatus,
} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {logUiError} from '@/lib/ui_logging';
import {RUNS_CHANGED_EVENT} from './dom_events';
import {
  HEADER_CONTROL_ICON_CLASSES,
  headerControlButtonClasses,
} from './layout_primitives';
import {tooltipClassNames} from './classes';

// Cancellation is terminal and cannot resume; require a second click without
// adding another modal.
const ARMED_MS = 4_000;

// A stale-status 409 means the run already ended; refreshing removes the
// control without reporting an error.
async function stopRun(runId: string): Promise<void> {
  try {
    await cancelRun(runId);
  } catch (error) {
    if (!(error instanceof HttpError && error.status === 409)) {
      logUiError('Failed to stop the run', String(error));
    }
  } finally {
    window.dispatchEvent(new Event(RUNS_CHANGED_EVENT));
  }
}

function useArmedStop(runId: string | undefined) {
  const [armed, setArmed] = useState(false);
  const [stopping, setStopping] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  // Disarm on run changes so confirmation cannot transfer to the wrong session.
  useEffect(() => {
    setArmed(false);
    return () => window.clearTimeout(timer.current);
  }, [runId]);

  async function activate(id: string) {
    if (!armed) {
      setArmed(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setArmed(false), ARMED_MS);
      return;
    }
    setStopping(true);
    await stopRun(id);
    setStopping(false);
    setArmed(false);
  }

  return {armed, stopping, activate};
}

function stopFace(armed: boolean): {
  label: string;
  tooltip: string;
  icon: IconName;
} {
  return armed
    ? {
        label: 'Confirm stop',
        tooltip: 'Stopping cannot be undone',
        icon: 'warning',
      }
    : {
        label: 'Stop run',
        tooltip: 'Stop this research session',
        icon: 'stop',
      };
}

// Stop belongs in the header because the same run is reachable from both chat
// and results.
export function CancelRunControl({
  runId,
  status,
}: {
  runId: string | undefined;
  status: RunStatus | undefined;
}) {
  const {armed, stopping, activate} = useArmedStop(runId);
  if (!runId || !isStoppableStatus(status)) return null;

  const face = stopFace(armed);
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: headerControlButtonClasses(),
        placement: 'left',
      })}
      data-tooltip={face.tooltip}
      aria-label={face.label}
      disabled={stopping}
      onClick={() => void activate(runId)}
    >
      <Icon
        aria-hidden="true"
        className={HEADER_CONTROL_ICON_CLASSES}
        name={face.icon}
      />
      <span>{face.label}</span>
    </button>
  );
}

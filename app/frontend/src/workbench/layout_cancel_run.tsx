import {useEffect, useRef, useState} from 'react';
import {
  cancelRun,
  HttpError,
  isTerminalStatus,
  type RunStatus,
} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {logUiError} from '@/lib/ui_logging';
import {RUNS_CHANGED_EVENT} from './dom_events';
import {
  HEADER_CONTROL_ICON_CLASSES,
  headerControlButtonClasses,
} from './layout_primitives';
import {tooltipClassNames} from './tooltip';

/**
 * How long the armed "Confirm stop" state stands before reverting.
 *
 * Stopping a run cannot be undone -- a cancelled run is terminal, and only
 * a *paused* run can be resumed -- so the control asks twice. It asks in
 * place rather than through a modal because this app has no confirm dialog
 * and the destructive control it does have (Clear logs) acts immediately;
 * a second click on the same pill is the smaller addition, and it matches
 * the ephemeral-label idiom the Copy control already uses.
 */
const ARMED_MS = 4_000;

/**
 * Stops the run, and reports anything but a stale-status race.
 *
 * A 409 is the run history's poll losing to the run's own ending: the
 * button was offered for a run that has since finished. Refreshing is the
 * entire remedy -- it takes the button away -- so there is nothing to
 * report. Either way the refresh fires, because that is what hides the
 * control.
 */
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

// The two-step arm state: idle, armed (waiting for the confirming click),
// and stopping. Held together so the button below reads as one control
// rather than three booleans.
function useArmedStop(runId: string | undefined) {
  const [armed, setArmed] = useState(false);
  const [stopping, setStopping] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  // Disarm whenever the control changes runs: an armed pill carried into
  // another session would stop the wrong run on a single click.
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

// Whether a run can still be stopped: anything the server would accept a
// cancel for. Deliberately not `isActiveStatus`, which excludes `paused` --
// that is the right reading for a progress indicator, and the wrong one
// here, since a paused run is precisely an unfinished run the scientist may
// want rid of. A draft has not started, so there is nothing to stop.
function isStoppable(status: RunStatus | undefined): boolean {
  return Boolean(status && status !== 'draft' && !isTerminalStatus(status));
}

// The control's two faces: the offer, and the armed confirmation. Named
// together so the label, the hover text and the icon cannot drift into
// disagreeing about which state the button is in.
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

/**
 * The header's stop control for the session's run, or nothing.
 *
 * Lives in the header rather than on the run page because the run is
 * reachable from both halves of a session: a scientist who wants to stop it
 * is as likely to be in the chat, still talking to it, as on the results
 * page watching it.
 *
 * @param runId The run this control stops.
 * @param status That run's status, from the shared run history (which polls
 *   while any run is active, so the control appears and disappears on its
 *   own). Anything terminal renders nothing.
 */
export function CancelRunControl({
  runId,
  status,
}: {
  runId: string | undefined;
  status: RunStatus | undefined;
}) {
  const {armed, stopping, activate} = useArmedStop(runId);
  if (!runId || !isStoppable(status)) return null;

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

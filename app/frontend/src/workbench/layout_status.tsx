import {Icon, type IconName} from '@/components/icon';
import type {SystemStatus} from '@/api/system';
import {useSystemStatus} from './hooks/use_system_status';
import {tooltipClassNames} from './tooltip';

const STATUS_CHIP_BASE_CLASSES =
  'ucs-system-status inline-flex h-[1.7rem] items-center gap-[0.3rem] ' +
  'rounded-full px-[0.62rem] text-[0.72rem] font-semibold whitespace-nowrap';

const STATUS_CHIP_NEUTRAL_CLASSES =
  'bg-cosci-logs-accent-bg text-cosci-logs-accent-fg';

const STATUS_CHIP_DANGER_CLASSES =
  'bg-cosci-logs-danger-bg text-cosci-logs-danger-fg';

/** What the header chip should say, or null to render nothing. */
export interface SystemStatusChip {
  label: string;
  detail: string;
  icon: IconName;
  danger: boolean;
}

/**
 * Derives the header chip from the latest system status.
 *
 * Shows nothing while loading or when a live model backend is configured;
 * the chip only appears when there is something worth flagging: the API
 * being unreachable, or runs executing against the deterministic offline
 * LLM backend (no live model calls, e.g. keyless/demo deployments).
 *
 * @param status The last /status payload, or null before the first.
 * @param unreachable Whether the most recent /status fetch failed.
 * @returns The chip contents, or null to render nothing.
 */
export function buildSystemStatusChip(
  status: SystemStatus | null,
  unreachable: boolean,
): SystemStatusChip | null {
  if (unreachable) {
    return {
      label: 'API offline',
      detail: 'The backend API is not reachable.',
      icon: 'warning',
      danger: true,
    };
  }
  if (status?.llm_backend === 'offline') {
    return {
      label: 'Offline mode',
      detail:
        'Runs use the deterministic offline LLM backend — the full agent ' +
        'pipeline runs, but no live model calls are made. Worker model ' +
        `when enabled: ${status.model_name}.`,
      icon: 'computer',
      danger: false,
    };
  }
  return null;
}

/**
 * Header offline-mode / API-health indicator, fed by the `/status` endpoint.
 *
 * Renders as a compact chip next to the Logs control; hidden entirely when
 * the backend is reachable and running against a live model backend.
 */
export function SystemStatusIndicator() {
  const {status, unreachable} = useSystemStatus();
  const chip = buildSystemStatusChip(status, unreachable);
  if (!chip) return null;

  const tone = chip.danger
    ? STATUS_CHIP_DANGER_CLASSES
    : STATUS_CHIP_NEUTRAL_CLASSES;
  return (
    <span
      role="status"
      className={tooltipClassNames({
        className: `${STATUS_CHIP_BASE_CLASSES} ${tone}`,
        placement: 'left',
      })}
      data-tooltip={chip.detail}
    >
      <Icon aria-hidden="true" className="text-[0.95rem]" name={chip.icon} />
      <span>{chip.label}</span>
    </span>
  );
}

import {Icon, type IconName} from '@/components/icon';
import {reportLabel, type ReportStatus} from './layout_diagnostics_report';
import {tooltipClassNames} from './tooltip';

const DIAGNOSTIC_HEADER_CLASSES =
  'ucs-diagnostic-header flex items-center justify-between gap-3 border-b ' +
  'border-cosci-logs-border px-4 py-3 ' +
  'max-[700px]:flex-col max-[700px]:items-start';

const DIAGNOSTIC_TITLE_CLASSES =
  'm-0 text-base font-semibold leading-tight text-cosci-logs-heading';

const DIAGNOSTIC_ACTIONS_CLASSES =
  'ucs-diagnostic-actions flex flex-nowrap gap-[0.45rem]';

const DIAGNOSTIC_ACTION_BUTTON_CLASSES =
  'inline-flex min-h-8 cursor-pointer items-center gap-[0.3rem] rounded-full ' +
  'border border-cosci-logs-action-border ' +
  'bg-cosci-logs-action-bg px-[0.75rem] text-[0.82rem] font-semibold ' +
  'whitespace-nowrap text-cosci-logs-action-fg ' +
  'hover:bg-cosci-logs-action-hover ' +
  'focus-visible:bg-cosci-logs-action-hover ' +
  // Dimmed and inert-looking when it cannot act, so "why is nothing
  // happening" is answered before the click rather than after it. The
  // tooltip still fires: :hover matches a disabled button, which is the
  // whole reason the explanation can live there.
  'disabled:cursor-default disabled:opacity-45 ' +
  'disabled:hover:bg-cosci-logs-action-bg';

// One Clear/Copy/Report button in the header's actions row. A disabled
// action keeps its tooltip so the reason it cannot be used is one hover
// away rather than a guess.
function DiagnosticActionButton({
  icon,
  label,
  onClick,
  disabled,
  tooltip,
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tooltip?: string;
}) {
  return (
    <button
      type="button"
      className={
        tooltip
          ? tooltipClassNames({
              className: DIAGNOSTIC_ACTION_BUTTON_CLASSES,
              placement: 'bottom',
              wrap: true,
            })
          : DIAGNOSTIC_ACTION_BUTTON_CLASSES
      }
      data-tooltip={tooltip}
      disabled={disabled}
      onClick={onClick}
    >
      <Icon aria-hidden="true" className="text-base" name={icon} />
      <span>{label}</span>
    </button>
  );
}

// One entry in the header's actions row.
interface DiagnosticAction {
  id: string;
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tooltip?: string;
}

// What the Report action offers, given whether the server can send mail at
// all. Disabled rather than hidden: the way to get diagnostics to the
// maintainer should be visible even on a deployment that cannot yet mail
// them, with the reason attached — and Copy is right beside it.
function reportAction(
  status: ReportStatus,
  canReport: boolean,
  onReport: () => void,
): DiagnosticAction {
  return {
    id: 'report',
    icon: 'send',
    label: reportLabel(status),
    onClick: onReport,
    disabled: !canReport || status === 'sending',
    tooltip: canReport
      ? 'Email these logs to the maintainer'
      : 'Email delivery is not configured on this server',
  };
}

// Popover header: the "Diagnostic Logs" title plus the Clear/Copy/Report
// actions.
export function DiagnosticLogsHeader({
  copied,
  reportStatus,
  canReport,
  onClear,
  onCopy,
  onReport,
}: {
  copied: boolean;
  reportStatus: ReportStatus;
  canReport: boolean;
  onClear: () => void;
  onCopy: () => void;
  onReport: () => void;
}) {
  const actions: DiagnosticAction[] = [
    {id: 'clear', icon: 'refresh', label: 'Clear', onClick: onClear},
    {
      id: 'copy',
      icon: 'content_copy',
      label: copied ? 'Copied' : 'Copy',
      onClick: onCopy,
    },
    reportAction(reportStatus, canReport, onReport),
  ];

  return (
    <div className={DIAGNOSTIC_HEADER_CLASSES}>
      <div className="ucs-diagnostic-title">
        <h2 className={DIAGNOSTIC_TITLE_CLASSES}>Diagnostic Logs</h2>
      </div>
      <div className={DIAGNOSTIC_ACTIONS_CLASSES}>
        {actions.map(action => (
          <DiagnosticActionButton key={action.id} {...action} />
        ))}
      </div>
    </div>
  );
}

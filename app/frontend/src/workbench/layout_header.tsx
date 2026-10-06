import type {RefObject} from 'react';
import {Link} from 'react-router-dom';
import type {RunStatus} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {isModifiedClick} from '@/workbench/dom_events';
import {GoogleLabsIcon, NAV_ICON_CLASSES} from './layout_primitives';
import {TruncatedLabel} from './components/truncated_label';
import {CancelRunControl} from './layout_cancel_run';
import {DiagnosticsControl} from './layout_diagnostics';
import {FeedbackControl} from './components/feedback_dialog';
import {SessionSwitch, type SessionSwitchData} from './layout_session_switch';
import {tooltipClassNames} from './classes';
import type {SystemStatus} from '@/api/system';
import {useSystemStatus} from './hooks/system_status_context';

const HEADER_CLASSES = 'ucs-header-action-bar';

const PRODUCT_LOCKUP_CLASSES = 'ucs-product-lockup';

const HEADER_TITLE_CLASSES = 'ucs-header-title';

const HEADER_ACTIONS_CLASSES = 'ucs-header-actions';

function HamburgerButton({
  navOpen,
  onClick,
}: {
  navOpen: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="ucs-nav-hamburger"
      aria-label="Open navigation"
      aria-expanded={navOpen}
      aria-controls="primary-navigation"
      onClick={onClick}
    >
      <Icon aria-hidden="true" className={NAV_ICON_CLASSES} name="menu" />
    </button>
  );
}

// Only ordinary link navigation resets this tab’s chat; modified clicks must
// preserve it.
function ProductLockup({onNewChat}: {onNewChat: () => void}) {
  return (
    <Link
      to="/"
      state={{cosciAction: 'new-chat'}}
      className={tooltipClassNames({
        className: PRODUCT_LOCKUP_CLASSES,
        placement: 'right',
      })}
      aria-label="Go to Co-Scientist home"
      data-tooltip="Home"
      onClick={event => {
        if (!isModifiedClick(event)) onNewChat();
      }}
    >
      <GoogleLabsIcon aria-hidden="true" />
      <span>Co-Scientist</span>
    </Link>
  );
}

export function ShellHeader({
  navOpen,
  toggleNav,
  startNewChat,
  headerTitle,
  logsControlRef,
  session,
  runStatus,
}: {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  headerTitle: string;
  logsControlRef: RefObject<HTMLDivElement | null>;
  session: SessionSwitchData | null;
  runStatus: RunStatus | undefined;
}) {
  return (
    <header className={HEADER_CLASSES}>
      <HamburgerButton navOpen={navOpen} onClick={toggleNav} />
      <ProductLockup onNewChat={startNewChat} />
      <div id="header-landing-tabs" className="ucs-header-landing-tabs" />
      <div className={HEADER_TITLE_CLASSES}>
        {headerTitle && (
          <TruncatedLabel
            className="block min-w-0 overflow-hidden whitespace-nowrap"
            text={headerTitle}
          />
        )}
      </div>
      {/* Navigation dismisses popovers itself, so the session switch may share this anchor. */}
      <div ref={logsControlRef} className={HEADER_ACTIONS_CLASSES}>
        <CancelRunControl runId={session?.runId} status={runStatus} />
        <SessionSwitch session={session} />
        <SystemStatusIndicator />
        <FeedbackControl runId={session?.runId} />
        <DiagnosticsControl />
      </div>
    </header>
  );
}

const STATUS_CHIP_BASE_CLASSES =
  'ucs-system-status inline-flex h-[1.7rem] items-center gap-[0.3rem] ' +
  'rounded-full px-[0.62rem] text-[0.72rem] font-semibold whitespace-nowrap';

const STATUS_CHIP_NEUTRAL_CLASSES =
  'bg-cosci-logs-accent-bg text-cosci-logs-accent-fg';

const STATUS_CHIP_DANGER_CLASSES =
  'bg-cosci-logs-danger-bg text-cosci-logs-danger-fg';

export interface SystemStatusChip {
  label: string;
  detail: string;
  icon: IconName;
  danger: boolean;
}

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
        placement: 'bottom',
        wrap: true,
      })}
      data-tooltip={chip.detail}
    >
      <Icon aria-hidden="true" className="text-[0.95rem]" name={chip.icon} />
      <span>{chip.label}</span>
    </span>
  );
}

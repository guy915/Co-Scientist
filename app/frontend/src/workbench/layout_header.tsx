import type {RefObject} from 'react';
import {Link} from 'react-router-dom';
import type {RunStatus} from '@/api/runs';
import {Icon, type IconName} from '@/components/icon';
import {isModifiedClick} from '@/workbench/dom_events';
import {
  GoogleLabsIcon,
  NAV_ICON_CLASSES,
  ShellPopover,
} from './layout_primitives';
import {TruncatedLabel} from './components/truncated_label';
import {CancelRunControl} from './layout_cancel_run';
import {DiagnosticsControl} from './layout_diagnostics';
import type {ShellPanel} from './layout';
import {SessionSwitch, type SessionSwitchData} from './layout_session_switch';
import {tooltipClassNames} from './tooltip';
import type {SystemStatus} from '@/api/system';
import {useSystemStatus} from './hooks/system_status_context';

const HEADER_CLASSES = 'ucs-header-action-bar';

const PRODUCT_LOCKUP_CLASSES = 'ucs-product-lockup';

const HEADER_TITLE_CLASSES = 'ucs-header-title';

const HEADER_ACTIONS_CLASSES = 'ucs-header-actions';

// Mobile drawer / desktop rail toggle; the header's leftmost control.
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

// The Co-Scientist wordmark/icon; doubles as a "go home" / new-chat control.
// A link, so it behaves like the home link it looks like under a Cmd or
// middle click; the session reset runs only on a plain click, which is the
// only click that navigates this tab (see isModifiedClick).
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

/**
 * Renders the header action bar: hamburger (mobile drawer / desktop rail
 * toggle), product lockup (doubles as "go home"), the page's dispatched
 * title, and the Logs/diagnostics control.
 *
 * @param navOpen Whether the nav rail/drawer is open.
 * @param toggleNav Toggles the nav rail/drawer.
 * @param startNewChat Resets the chat workspace and navigates home.
 * @param headerTitle The page-dispatched title override, if any.
 * @param activePanel The currently open header popover, if any.
 * @param onTogglePanel Opens/closes the given popover.
 * @param logsControlRef Anchor ref for outside-click dismissal of the Logs
 *   popover.
 * @param session The session this route is one half of, switched between by
 *   the Chat/Results control; null when there is no other half.
 * @param runStatus Status of that session's run, when it has one, which is
 *   what decides whether the Stop control is offered.
 */
export function ShellHeader({
  navOpen,
  toggleNav,
  startNewChat,
  headerTitle,
  activePanel,
  onTogglePanel,
  logsControlRef,
  session,
  runStatus,
}: {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  headerTitle: string;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  logsControlRef: RefObject<HTMLDivElement | null>;
  session: SessionSwitchData | null;
  runStatus: RunStatus | undefined;
}) {
  return (
    <header className={HEADER_CLASSES}>
      <HamburgerButton navOpen={navOpen} onClick={toggleNav} />
      <ProductLockup onNewChat={startNewChat} />
      <div className={HEADER_TITLE_CLASSES}>
        {headerTitle && (
          <TruncatedLabel
            className="block min-w-0 overflow-hidden whitespace-nowrap"
            text={headerTitle}
          />
        )}
      </div>
      {/* Inside the Logs anchor rather than beside it: the switch wears the
          same pill as the controls it sits with, and a click on it navigates,
          which closes any open popover on its own (see
          useDismissChromeOnNavigate). */}
      <div ref={logsControlRef} className={HEADER_ACTIONS_CLASSES}>
        <CancelRunControl runId={session?.runId} status={runStatus} />
        <SessionSwitch session={session} />
        <SystemStatusIndicator />
        <DiagnosticsControl
          open={activePanel === 'logs'}
          onToggle={() => onTogglePanel('logs')}
          renderPopover={(children, className, ariaLabel) => (
            <ShellPopover
              className={className}
              role="group"
              ariaLabel={ariaLabel}
            >
              {children}
            </ShellPopover>
          )}
        />
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

import {type ReactNode, type RefObject} from 'react';
import {Icon} from '@/components/icon';
import {useAudience} from './audience_context';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {TruncatedLabel} from './components/truncated_label';
import {DiagnosticsControl} from './layout_diagnostics';
import {GoogleTeamControl} from './layout_google_control';
import {type ShellPanel} from './layout_hooks';
import {PilotControl} from './layout_pilot_control';
import {NAV_ICON_CLASSES, ShellPopover} from './layout_primitives';
import {SystemStatusIndicator} from './layout_status';
import {tooltipClassNames} from './tooltip';

// The header's rightmost control depends on the selected audience: the Google
// team sees a personal note, SBI/UCD pilots see an early-access guide, and
// everyone else sees the diagnostics Logs popover. All three share the shell's
// popover slot ('logs') so they stay mutually exclusive with Settings.
function AudienceHeaderControl({
  activePanel,
  onTogglePanel,
  activeRunId,
}: {
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  activeRunId?: string;
}) {
  const {audience} = useAudience();
  const open = activePanel === 'logs';
  const onToggle = () => onTogglePanel('logs');
  const renderPopover = (children: ReactNode, className: string) => (
    <ShellPopover className={className}>{children}</ShellPopover>
  );
  if (audience === 'google') {
    return (
      <GoogleTeamControl
        open={open}
        onToggle={onToggle}
        renderPopover={renderPopover}
      />
    );
  }
  if (audience === 'sbi_ucd') {
    return (
      <PilotControl
        open={open}
        onToggle={onToggle}
        renderPopover={renderPopover}
      />
    );
  }
  return (
    <DiagnosticsControl
      open={open}
      onToggle={onToggle}
      runId={activeRunId}
      renderPopover={renderPopover}
    />
  );
}

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
function ProductLockup({onClick}: {onClick: () => void}) {
  return (
    <button
      type="button"
      className={tooltipClassNames({
        className: PRODUCT_LOCKUP_CLASSES,
        placement: 'right',
      })}
      aria-label="Go to Co-Scientist home"
      data-tooltip="Home"
      onClick={onClick}
    >
      <GoogleLabsIcon aria-hidden="true" />
      <span>Co-Scientist</span>
    </button>
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
 * @param activeRunId The run id from the active /runs/:id route, if any;
 *   lets the Logs popover load that run's persisted event timeline.
 * @param logsControlRef Anchor ref for outside-click dismissal of the Logs
 *   popover.
 */
export function ShellHeader({
  navOpen,
  toggleNav,
  startNewChat,
  headerTitle,
  activePanel,
  onTogglePanel,
  activeRunId,
  logsControlRef,
}: {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  headerTitle: string;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  activeRunId?: string;
  logsControlRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <header className={HEADER_CLASSES}>
      <HamburgerButton navOpen={navOpen} onClick={toggleNav} />
      <ProductLockup onClick={startNewChat} />
      <div className={HEADER_TITLE_CLASSES}>
        {headerTitle && (
          <TruncatedLabel
            className="block min-w-0 overflow-hidden whitespace-nowrap"
            text={headerTitle}
          />
        )}
      </div>
      <div ref={logsControlRef} className={HEADER_ACTIONS_CLASSES}>
        <SystemStatusIndicator />
        <AudienceHeaderControl
          activePanel={activePanel}
          onTogglePanel={onTogglePanel}
          activeRunId={activeRunId}
        />
      </div>
    </header>
  );
}

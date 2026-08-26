import {type ReactNode, type RefObject} from 'react';
import {Link} from 'react-router-dom';
import {Icon} from '@/components/icon';
import {isModifiedClick} from '@/lib/modified_click';
import {type Audience, useAudience} from './audience_context';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {TruncatedLabel} from './components/truncated_label';
import {DiagnosticsControl} from './layout_diagnostics';
import {GoogleTeamControl} from './layout_google_control';
import {type ShellPanel} from './layout_hooks';
import {PilotControl} from './layout_pilot_control';
import {
  NAV_ICON_CLASSES,
  ShellPopover,
  type HeaderControlProps,
} from './layout_primitives';
import {SessionSwitch, type SessionSwitchData} from './layout_session_switch';
import {SystemStatusIndicator} from './layout_status';
import {tooltipClassNames} from './tooltip';

// The shape the three header controls share: an open flag, a toggle request,
// and the shell's popover wrapper.
type HeaderControl = (props: HeaderControlProps) => ReactNode;

// The single audience-specific header control, which REPLACES the Logs
// button rather than sitting beside it: the Google team gets a personal note,
// SBI/UCD pilots a feedback form, and the general audience the diagnostics
// Logs popover. One entry per audience, so exactly one control is shown --
// a pilot sees Feedback where a general user sees Logs, never both -- and the
// table is keyed by Audience so a new audience is a compile error here rather
// than a silent fallthrough to Logs. The team/pilot controls sit on the
// shell's 'audience' popover slot and Logs on its own 'logs' slot; the shell's
// single-open-panel rule keeps them mutually exclusive with every other
// header popover.
const AUDIENCE_CONTROLS: Record<
  Audience,
  {Control: HeaderControl; panel: ShellPanel}
> = {
  general: {Control: DiagnosticsControl, panel: 'logs'},
  google: {Control: GoogleTeamControl, panel: 'audience'},
  sbi_ucd: {Control: PilotControl, panel: 'audience'},
};

function AudienceHeaderControl({
  activePanel,
  onTogglePanel,
}: {
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
}) {
  // An unanswered affiliation question reads as the plain general workspace,
  // the same as everywhere else the audience is consumed.
  const {audience} = useAudience();
  const {Control, panel} = AUDIENCE_CONTROLS[audience ?? 'general'];
  return (
    <Control
      open={activePanel === panel}
      onToggle={() => onTogglePanel(panel)}
      renderPopover={(children, className, ariaLabel) => (
        <ShellPopover className={className} role="group" ariaLabel={ariaLabel}>
          {children}
        </ShellPopover>
      )}
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
}: {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  headerTitle: string;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
  logsControlRef: RefObject<HTMLDivElement | null>;
  session: SessionSwitchData | null;
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
        <SessionSwitch session={session} />
        <SystemStatusIndicator />
        <AudienceHeaderControl
          activePanel={activePanel}
          onTogglePanel={onTogglePanel}
        />
      </div>
    </header>
  );
}

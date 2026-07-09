import {type RefObject} from 'react';
import {Icon} from '@/components/icon';
import {GoogleLabsIcon} from './components/google_labs_icon';
import {TruncatedLabel} from './components/truncated_label';
import {DiagnosticsControl} from './layout_diagnostics';
import {type ShellPanel} from './layout_hooks';
import {NAV_ICON_CLASSES, ShellPopover} from './layout_primitives';
import {tooltipClassNames} from './tooltip';

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
  logsControlRef,
}: {
  navOpen: boolean;
  toggleNav: () => void;
  startNewChat: () => void;
  headerTitle: string;
  activePanel: ShellPanel | null;
  onTogglePanel: (panel: ShellPanel) => void;
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
        <DiagnosticsControl
          open={activePanel === 'logs'}
          onToggle={() => onTogglePanel('logs')}
          renderPopover={(children, className) => (
            <ShellPopover className={className}>{children}</ShellPopover>
          )}
        />
      </div>
    </header>
  );
}

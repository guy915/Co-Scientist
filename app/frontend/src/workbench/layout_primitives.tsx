import {type ReactNode} from 'react';
import {Link} from 'react-router-dom';
import {Icon, type IconName} from '@/components/icon';
import {tooltipClassNames} from './tooltip';

const SHELL_POPOVER_CLASSES = 'ucs-popover';

/**
 * Wraps popover content in the shell's positioned popover container,
 * naming it for assistive tech (see ShellPopover -- these panels are
 * interactive content, not a status announcement, so the name has to come
 * from a real accessible name rather than an implicit live-region role).
 */
export type RenderPopover = (
  children: ReactNode,
  className: string,
  ariaLabel: string,
) => ReactNode;

/**
 * The shape the header controls share: an open flag, a toggle request, and
 * the shell's popover wrapper.
 */
export interface HeaderControlProps {
  /** Whether the popover is shown; owned by the parent shell. */
  open: boolean;
  /** Requests the parent flip `open`. */
  onToggle: () => void;
  /** Wraps the panel content in the shell's positioned popover container. */
  renderPopover: RenderPopover;
}

/**
 * Icon sizing/coloring class shared by the shell's header and nav-rail
 * buttons (hamburger, rail actions).
 */
export const NAV_ICON_CLASSES = 'ucs-nav-icon';

/**
 * Trigger chrome shared by the header's right-side controls (the Logs,
 * Google-note, and pilot-feedback pills): an accent pill whose expanded
 * state holds the hover tint.
 *
 * @param padding The control's padding utilities, passed as complete class
 *   names so Tailwind's scanner sees them at the call site. The Logs
 *   trigger tightens its right side around the count badge; the default
 *   is the plain pill padding.
 */
export function headerControlButtonClasses(padding = 'px-[0.72rem]'): string {
  return (
    'ucs-logs-button relative inline-flex h-[2.35rem] min-w-max ' +
    'cursor-pointer items-center gap-[0.45rem] rounded-full border-0 ' +
    `bg-cosci-logs-accent-bg ${padding} font-[inherit] text-[0.88rem] ` +
    'font-semibold whitespace-nowrap text-cosci-logs-accent-fg ' +
    'hover:bg-cosci-logs-accent-hover ' +
    '[&[aria-expanded=true]]:bg-cosci-logs-accent-hover'
  );
}

// The plain pill, for a control that does not tighten its own padding.
const DEFAULT_HEADER_CONTROL_CLASSES = headerControlButtonClasses();

// Leading-icon sizing, shared by every header control so the three pills
// line up whatever icon they carry.
const HEADER_CONTROL_ICON_CLASSES = 'text-[1.05rem]';

/**
 * The header controls' shared trigger: the accent pill above, carrying a
 * leading icon, a label, and the caller's open state.
 *
 * @param props.icon The pill's leading icon.
 * @param props.label The pill's visible label.
 * @param props.tooltip Hover text, rendered by the CSS-only tooltip.
 * @param props.open Whether this control's popover is shown.
 * @param props.onToggle Requests the parent flip `open`.
 * @param props.ariaLabel An accessible name replacing the visible label,
 *   for a control whose label alone does not name it (Logs adds its count).
 *   Left off, the label names the button.
 * @param props.className The pill's own classes, when the control needs
 *   padding other than the default; pass a complete class name so
 *   Tailwind's scanner sees it at the call site.
 * @param props.children Content after the label, e.g. the Logs count badge.
 */
interface HeaderControlTriggerProps {
  icon: IconName;
  label: string;
  tooltip: string;
  open: boolean;
  onToggle: () => void;
  ariaLabel?: string;
  className?: string;
  children?: ReactNode;
}

/**
 * A header control that navigates instead of opening a popover, wearing the
 * same pill as {@link HeaderControlTrigger} so the header keeps one look.
 *
 * Deliberately carries no `aria-expanded`: it is a destination, not a
 * disclosure, and announcing it as collapsed would promise a panel that
 * never arrives.
 *
 * @param props.icon The pill's leading icon.
 * @param props.label The pill's visible label, which also names the link.
 * @param props.to The in-app route the pill navigates to.
 */
export function HeaderControlLink({
  icon,
  label,
  to,
}: {
  icon: IconName;
  label: string;
  to: string;
}) {
  return (
    <Link
      className={tooltipClassNames({
        // no-underline: the pill this replaces was a button, and the
        // anchor's default underline reads as a stray rule through the
        // label rather than as an affordance the pill needs.
        className: `${DEFAULT_HEADER_CONTROL_CLASSES} no-underline`,
        placement: 'left',
      })}
      to={to}
      data-tooltip={label}
    >
      <Icon
        aria-hidden="true"
        className={HEADER_CONTROL_ICON_CLASSES}
        name={icon}
      />
      <span>{label}</span>
    </Link>
  );
}

export function HeaderControlTrigger({
  icon,
  label,
  tooltip,
  open,
  onToggle,
  ariaLabel,
  className = DEFAULT_HEADER_CONTROL_CLASSES,
  children,
}: HeaderControlTriggerProps) {
  return (
    <button
      type="button"
      className={tooltipClassNames({className, placement: 'left'})}
      aria-label={ariaLabel}
      data-tooltip={tooltip}
      aria-expanded={open}
      onClick={onToggle}
    >
      <Icon
        aria-hidden="true"
        className={HEADER_CONTROL_ICON_CLASSES}
        name={icon}
      />
      <span>{label}</span>
      {children}
    </button>
  );
}

/**
 * Positioning/frame shared by the header controls' popovers; only the
 * width differs per control.
 *
 * @param width The control's width utility, passed as one complete class
 *   name so Tailwind's scanner sees it at the call site.
 */
export function headerControlPopoverClasses(width: string): string {
  return `ucs-popover--logs top-[calc(100%+0.45rem)] right-0 ${width} !p-0`;
}

/**
 * Shared popover shell for the Settings menu, the Logs panel, and the
 * audience-specific header controls; the caller supplies extra
 * positioning/sizing classes via `className`.
 *
 * Every one of these panels is interactive content the person opened on
 * purpose (a menu, a log list with its own controls, a form), not a status
 * message -- `role="status"` would make it an implicit live region, so a
 * screen reader announces the whole panel on open and again on every
 * change inside it. A caller that needs the panel named for assistive tech
 * passes `role`/`ariaLabel`; the rail's Settings menu needs neither, since
 * its own `role="menu"` child already carries the semantics.
 *
 * @param children The popover's content.
 * @param className Extra positioning/sizing classes for this popover.
 * @param role The container's accessible role, when it needs one.
 * @param ariaLabel The container's accessible name, paired with `role`.
 */
export function ShellPopover({
  children,
  className,
  role,
  ariaLabel,
}: {
  children: ReactNode;
  className: string;
  role?: 'group' | 'dialog';
  ariaLabel?: string;
}) {
  return (
    <div
      className={`${SHELL_POPOVER_CLASSES} ${className}`}
      role={role}
      aria-label={ariaLabel}
    >
      {children}
    </div>
  );
}

import {type ReactNode} from 'react';

const SHELL_POPOVER_CLASSES = 'ucs-popover';

/**
 * Icon sizing/coloring class shared by the shell's header and nav-rail
 * buttons (hamburger, rail actions).
 */
export const NAV_ICON_CLASSES = 'ucs-nav-icon';

/**
 * Shared popover shell for both the Settings menu and the Logs panel; the
 * caller supplies extra positioning/sizing classes via `className`.
 *
 * @param children The popover's content.
 * @param className Extra positioning/sizing classes for this popover.
 */
export function ShellPopover({
  children,
  className,
}: {
  children: ReactNode;
  className: string;
}) {
  return (
    <div className={`${SHELL_POPOVER_CLASSES} ${className}`} role="status">
      {children}
    </div>
  );
}

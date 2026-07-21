import {type ReactNode} from 'react';

const SHELL_POPOVER_CLASSES = 'ucs-popover';

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

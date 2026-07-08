import type {ReactNode} from 'react';
import {Link} from 'react-router-dom';

// MD3 filled-button look on a router <Link>: pill radius, primary tonal
// colors via --md-sys-color-* vars, full-width below the sm breakpoint.
const BUTTON_CLASSES =
  'inline-flex min-h-12 items-center justify-center rounded-full border border-transparent bg-[var(--md-sys-color-primary)] px-[1.35rem] py-[0.72rem] text-sm font-semibold leading-none text-[var(--md-sys-color-on-primary)] no-underline hover:opacity-90 max-sm:w-full focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-[var(--md-sys-color-primary)]';

/**
 * Renders a styled router link used as a call-to-action on public pages.
 *
 * @param props The destination and link contents.
 */
export function PublicLinkButton({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link className={BUTTON_CLASSES} to={to}>
      {children}
    </Link>
  );
}

import type {ReactNode} from 'react';
import {Link} from 'react-router-dom';

const BASE_CLASSES =
  'inline-flex min-h-12 items-center justify-center rounded-full border px-[1.35rem] py-[0.72rem] text-sm font-semibold leading-none no-underline max-sm:w-full focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-[var(--md-sys-color-primary)]';

const VARIANT_CLASSES = {
  filled:
    'border-transparent bg-[var(--md-sys-color-primary)] text-[var(--md-sys-color-on-primary)] hover:opacity-90',
  outline:
    'border-[var(--md-sys-color-outline)] bg-transparent text-[var(--md-sys-color-on-surface)] hover:border-[var(--md-sys-color-primary)] hover:bg-[var(--md-sys-color-secondary-container)]',
};

/**
 * Renders a styled router link used as a call-to-action on public pages.
 *
 * @param props The destination, visual variant, and link contents.
 */
export function PublicLinkButton({
  to,
  variant = 'filled',
  children,
}: {
  to: string;
  variant?: 'filled' | 'outline';
  children: ReactNode;
}) {
  return (
    <Link className={`${BASE_CLASSES} ${VARIANT_CLASSES[variant]}`} to={to}>
      {children}
    </Link>
  );
}

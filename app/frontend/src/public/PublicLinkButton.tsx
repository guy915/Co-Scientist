import type {ReactNode} from 'react';
import {Link} from 'react-router-dom';

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
    <Link className={`public-button public-button--${variant}`} to={to}>
      {children}
    </Link>
  );
}

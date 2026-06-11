import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function PublicLinkButton({
  to,
  variant = "filled",
  children,
}: {
  to: string;
  variant?: "filled" | "outline";
  children: ReactNode;
}) {
  return (
    <Link className={`public-button public-button--${variant}`} to={to}>
      {children}
    </Link>
  );
}

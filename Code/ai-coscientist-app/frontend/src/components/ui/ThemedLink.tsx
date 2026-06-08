import { useState } from "react";
import { cn } from "@/lib/utils";

interface ThemedLinkProps extends React.AnchorHTMLAttributes<HTMLAnchorElement> {
  children: React.ReactNode;
}

/**
 * link component that uses theme-aware colors
 */
export function ThemedLink({ children, className, ...props }: ThemedLinkProps) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <a
      {...props}
      className={cn("cursor-pointer", className)}
      style={{
        color: isHovered ? "var(--color-th-link-hover)" : "var(--color-th-link)",
        ...props.style,
      }}
      onMouseEnter={(e) => {
        setIsHovered(true);
        props.onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        setIsHovered(false);
        props.onMouseLeave?.(e);
      }}
    >
      {children}
    </a>
  );
}

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent",
        secondary: "border-transparent",
        destructive: "border-transparent",
        outline: "",
        success: "border-transparent",
        warning: "border-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

const variantStyles: Record<string, React.CSSProperties> = {
  default: {
    backgroundColor: "var(--color-th-primary)",
    color: "var(--color-th-primary-fg)",
  },
  secondary: {
    backgroundColor: "var(--color-th-secondary)",
    color: "var(--color-th-secondary-fg)",
  },
  destructive: {
    backgroundColor: "var(--color-th-destructive)",
    color: "var(--color-th-destructive-fg)",
  },
  outline: {
    backgroundColor: "transparent",
    color: "var(--color-th-fg)",
    borderColor: "var(--color-th-border)",
  },
  success: {
    backgroundColor: "var(--color-th-success)",
    color: "var(--color-th-success-fg)",
  },
  warning: {
    backgroundColor: "var(--color-th-warning)",
    color: "var(--color-th-warning-fg)",
  },
};

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, style, ...props }: BadgeProps) {
  const variantStyle = variantStyles[variant || "default"] || variantStyles.default;
  return (
    <div
      className={cn(badgeVariants({ variant }), className)}
      style={{ ...variantStyle, ...style }}
      {...props}
    />
  );
}

export { Badge, badgeVariants };

import "@material/web/button/filled-button.js";
import "@material/web/button/filled-tonal-button.js";
import "@material/web/button/outlined-button.js";
import "@material/web/button/text-button.js";
import "@material/web/iconbutton/icon-button.js";
import type React from "react";

export type ButtonVariant = "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";

export type ButtonSize = "default" | "sm" | "lg" | "icon";

export interface ButtonProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  onClick?: React.MouseEventHandler<HTMLElement>;
  onMouseEnter?: React.MouseEventHandler<HTMLElement>;
  onMouseLeave?: React.MouseEventHandler<HTMLElement>;
  className?: string;
  style?: React.CSSProperties;
  type?: "button" | "submit" | "reset";
  "aria-label"?: string;
  "aria-expanded"?: boolean | "true" | "false";
  "aria-haspopup"?: boolean | "true" | "false" | "menu" | "listbox" | "tree" | "grid" | "dialog";
  children?: React.ReactNode;
  "trailing-icon"?: boolean;
}

function sizeStyle(size: ButtonSize | undefined): React.CSSProperties {
  switch (size) {
    case "sm":
      return {
        "--md-filled-button-container-height": "32px",
        fontSize: "0.75rem",
      } as React.CSSProperties;
    case "lg":
      return {
        "--md-filled-button-container-height": "40px",
        paddingInline: "2rem",
      } as React.CSSProperties;
    case "icon":
      return { width: "36px", height: "36px" } as React.CSSProperties;
    default:
      return {};
  }
}

export function Button({
  variant = "default",
  size,
  disabled,
  onClick,
  onMouseEnter,
  onMouseLeave,
  className,
  style,
  type,
  children,
  ...rest
}: ButtonProps) {
  const handlers = {
    onclick: onClick as unknown as EventListener,
    onmouseenter: onMouseEnter as unknown as EventListener,
    onmouseleave: onMouseLeave as unknown as EventListener,
  };
  const sharedWithoutType = {
    disabled: disabled || undefined,
    class: className,
    style: { ...sizeStyle(size), ...style },
    ...rest,
  };

  if (size === "icon") {
    return (
      <md-icon-button {...handlers} {...sharedWithoutType}>
        {children}
      </md-icon-button>
    );
  }

  switch (variant) {
    case "destructive":
      return (
        <md-filled-button
          type={type}
          {...handlers}
          {...sharedWithoutType}
          style={
            {
              ...sharedWithoutType.style,
              "--md-filled-button-container-color": "var(--md-sys-color-error)",
              "--md-filled-button-label-text-color": "var(--md-sys-color-on-error)",
              "--md-filled-button-hover-label-text-color": "var(--md-sys-color-on-error)",
              "--md-filled-button-pressed-label-text-color": "var(--md-sys-color-on-error)",
              "--md-filled-button-focus-label-text-color": "var(--md-sys-color-on-error)",
            } as React.CSSProperties
          }
        >
          {children}
        </md-filled-button>
      );
    case "outline":
      return (
        <md-outlined-button type={type} {...handlers} {...sharedWithoutType}>
          {children}
        </md-outlined-button>
      );
    case "secondary":
      return (
        <md-filled-tonal-button type={type} {...handlers} {...sharedWithoutType}>
          {children}
        </md-filled-tonal-button>
      );
    case "ghost":
    case "link":
      return (
        <md-text-button type={type} {...handlers} {...sharedWithoutType}>
          {children}
        </md-text-button>
      );
    default:
      return (
        <md-filled-button type={type} {...handlers} {...sharedWithoutType}>
          {children}
        </md-filled-button>
      );
  }
}

export { Button as default };

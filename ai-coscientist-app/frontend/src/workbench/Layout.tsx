import "@material/web/icon/icon.js";
import "@material/web/button/outlined-button.js";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { LogConsole } from "./components/LogConsole";
import { ThemeToggle } from "./components/ThemeToggle";

export function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ backgroundColor: "var(--color-th-bg)", color: "var(--color-th-fg)" }}
    >
      <header
        className="border-b sticky top-0 z-30 backdrop-blur-xl"
        style={{
          backgroundColor:
            "color-mix(in srgb, var(--md-sys-color-surface-container) 70%, transparent)",
          borderColor: "var(--color-th-border)",
        }}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-2">
          <Link to="/" className="flex items-center gap-2 font-semibold shrink-0">
            {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
            <md-icon aria-hidden="true" style={{ color: "var(--md-sys-color-primary)" }}>
              science
            </md-icon>
            <span className="text-base tracking-tight">AI Co-Scientist</span>
          </Link>
          <nav className="flex items-center gap-2 sm:gap-3 text-sm">
            <span className="hidden sm:inline-flex">
              <ThemeToggle />
            </span>
            <md-outlined-button
              onclick={(() => navigate("/")) as EventListener}
              style={
                location.pathname === "/"
                  ? ({
                      "--md-outlined-button-outline-width": "1px",
                      "--md-outlined-button-outline-color": "var(--md-sys-color-primary)",
                      "--md-outlined-button-label-text-color": "var(--md-sys-color-primary)",
                    } as React.CSSProperties)
                  : ({
                      "--md-outlined-button-outline-width": "1px",
                      "--md-outlined-button-outline-color": "var(--color-th-border)",
                      "--md-outlined-button-label-text-color": "var(--color-th-muted-fg)",
                    } as React.CSSProperties)
              }
            >
              Dashboard
            </md-outlined-button>
            <span className="hidden sm:inline-flex">
              <LogConsole />
            </span>
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-4 sm:py-6 wb-fade-in">
        {children}
      </main>
      <footer
        className="text-sm py-4 border-t text-center"
        style={{
          borderColor: "var(--color-th-border)",
          color: "var(--color-th-muted-fg)",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        &copy; 2026 AI Co-Scientist
      </footer>
    </div>
  );
}

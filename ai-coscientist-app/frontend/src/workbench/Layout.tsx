import "@material/web/icon/icon.js";
import "@material/web/button/outlined-button.js";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { LogConsole } from "./components/LogConsole";

export function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ backgroundColor: "var(--color-th-bg)", color: "var(--color-th-fg)" }}
    >
      <header
        className="border-b sticky top-0 z-30 backdrop-blur"
        style={{
          backgroundColor: "var(--md-sys-color-surface-container)",
          borderColor: "var(--color-th-border)",
        }}
      >
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
            <md-icon aria-hidden="true" style={{ color: "var(--md-sys-color-primary)" }}>
              science
            </md-icon>
            <span className="text-base tracking-tight">AI Co-Scientist</span>
          </Link>
          <nav className="flex items-center gap-3 text-sm">
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
            <LogConsole />
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-6 wb-fade-in">{children}</main>
      <footer
        className="text-xs py-3 border-t text-center"
        style={{
          borderColor: "var(--color-th-border)",
          color: "var(--color-th-muted-fg)",
        }}
      >
        Open clone of Google DeepMind&rsquo;s AI Co-Scientist · runs locally · scientific use only
      </footer>
    </div>
  );
}

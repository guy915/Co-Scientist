import "@material/web/icon/icon.js";
import "@material/web/button/filled-button.js";
import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { LogConsole } from "./components/LogConsole";
import { MockBanner } from "./components/MockBanner";
import { ShortcutsHint } from "./components/ShortcutsHint";
import { ThemeToggle } from "./components/ThemeToggle";

export function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
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
            <span
              className="text-xs px-1.5 py-0.5 rounded ml-1"
              style={{
                backgroundColor: "var(--color-th-secondary)",
                color: "var(--color-th-secondary-fg)",
              }}
            >
              clone
            </span>
          </Link>
          <nav className="flex items-center gap-3 text-sm">
            <NavLink
              to="/"
              end
              className={({ isActive }) => `hover:underline ${isActive ? "font-semibold" : ""}`}
            >
              Dashboard
            </NavLink>
            <ShortcutsHint />
            <LogConsole />
            <ThemeToggle />
            <md-filled-button onclick={(() => navigate("/runs/new")) as EventListener}>
              {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
              <md-icon slot="icon" aria-hidden="true">
                add
              </md-icon>
              New run
            </md-filled-button>
          </nav>
        </div>
        <MockBanner />
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

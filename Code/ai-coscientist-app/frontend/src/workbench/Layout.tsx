import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { Beaker, Plus } from "lucide-react";
import { MockBanner } from "./components/MockBanner";
import { ThemeToggle } from "./components/ThemeToggle";
import { ShortcutsHint } from "./components/ShortcutsHint";

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ backgroundColor: "var(--color-th-bg)", color: "var(--color-th-fg)" }}
    >
      <header
        className="border-b sticky top-0 z-30 backdrop-blur"
        style={{
          backgroundColor: "color-mix(in srgb, var(--color-th-bg) 92%, transparent)",
          borderColor: "var(--color-th-border)",
        }}
      >
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <Beaker
              className="w-5 h-5"
              style={{ color: "var(--color-th-primary)" }}
              aria-hidden="true"
            />
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
              className={({ isActive }) =>
                `hover:underline ${isActive ? "font-semibold" : ""}`
              }
            >
              Dashboard
            </NavLink>
            <ShortcutsHint />
            <ThemeToggle />
            <Link
              to="/runs/new"
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm transition-opacity hover:opacity-90"
              style={{
                backgroundColor: "var(--color-th-primary)",
                color: "var(--color-th-primary-fg)",
              }}
            >
              <Plus className="w-4 h-4" aria-hidden="true" /> New run
            </Link>
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

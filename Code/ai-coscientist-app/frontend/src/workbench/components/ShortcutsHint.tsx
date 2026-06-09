import { useEffect, useState } from "react";
import { Keyboard, X } from "lucide-react";

const SHORTCUTS: { keys: string; description: string }[] = [
  { keys: "?", description: "Open this shortcut help" },
  { keys: "g d", description: "Go to dashboard" },
  { keys: "g n", description: "Start a new run" },
  { keys: "← / →", description: "Move between tabs (on a run page)" },
  { keys: "Esc", description: "Close any open dialog" },
];

export function ShortcutsHint() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Don't capture when typing in inputs/textareas.
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (press ?)"
        onClick={() => setOpen(true)}
        className="p-1.5 rounded border transition-colors"
        style={{
          borderColor: "var(--color-th-border)",
          backgroundColor: "var(--color-th-bg)",
          color: "var(--color-th-fg)",
        }}
      >
        <Keyboard className="w-4 h-4" aria-hidden="true" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-6"
          style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
          onClick={() => setOpen(false)}
        >
          <div
            className="max-w-md w-full rounded-lg border shadow-lg wb-fade-in"
            style={{
              backgroundColor: "var(--color-th-card)",
              borderColor: "var(--color-th-border)",
              color: "var(--color-th-fg)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <header
              className="flex items-center justify-between p-4 border-b"
              style={{ borderColor: "var(--color-th-border)" }}
            >
              <h2 className="text-base font-semibold">Keyboard shortcuts</h2>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setOpen(false)}
                className="p-1 rounded hover:bg-[color:var(--color-th-secondary)]"
              >
                <X className="w-4 h-4" />
              </button>
            </header>
            <ul className="p-4 space-y-2 text-sm">
              {SHORTCUTS.map((s) => (
                <li key={s.keys} className="flex items-center justify-between">
                  <span style={{ color: "var(--color-th-muted-fg)" }}>{s.description}</span>
                  <kbd
                    className="text-xs font-mono px-1.5 py-0.5 rounded border"
                    style={{
                      borderColor: "var(--color-th-border)",
                      backgroundColor: "var(--color-th-secondary)",
                    }}
                  >
                    {s.keys}
                  </kbd>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}

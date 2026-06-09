import { Moon, Sun } from "lucide-react";
import { useTheme } from "../ThemeContext";

export function ThemeToggle() {
  const { mode, toggle } = useTheme();
  const isDark = mode === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Light mode" : "Dark mode"}
      className="p-1.5 rounded border transition-colors"
      style={{
        borderColor: "var(--color-th-border)",
        backgroundColor: "var(--color-th-bg)",
        color: "var(--color-th-fg)",
      }}
    >
      {isDark ? (
        <Sun className="w-4 h-4" aria-hidden="true" />
      ) : (
        <Moon className="w-4 h-4" aria-hidden="true" />
      )}
    </button>
  );
}

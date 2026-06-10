import "@material/web/iconbutton/icon-button.js";
import "@material/web/icon/icon.js";
import { useTheme } from "../ThemeContext";

export function ThemeToggle() {
  const { mode, toggle } = useTheme();
  const isDark = mode === "dark";
  return (
    <md-icon-button
      onclick={toggle as EventListener}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Light mode" : "Dark mode"}
    >
      {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
      <md-icon aria-hidden="true">{isDark ? "light_mode" : "dark_mode"}</md-icon>
    </md-icon-button>
  );
}

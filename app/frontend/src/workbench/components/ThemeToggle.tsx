import '@material/web/iconbutton/icon-button.js';
import '@material/web/icon/icon.js';
import {useTheme} from '../ThemeContext';

/**
 * Renders an icon button that toggles between light and dark theme.
 */
export function ThemeToggle() {
  const {mode, toggle} = useTheme();
  const isDark = mode === 'dark';
  return (
    <md-icon-button
      onclick={toggle as EventListener}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      <md-icon aria-hidden="true">
        {isDark ? 'dark_mode' : 'light_mode'}
      </md-icon>
    </md-icon-button>
  );
}

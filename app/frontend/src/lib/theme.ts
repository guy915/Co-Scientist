import {
  applyTheme,
  argbFromHex,
  themeFromSourceColor,
} from '@material/material-color-utilities';

// The single MD3 source color for the whole app (a teal). Every
// --md-sys-color-* token is derived from it at runtime, so palette changes
// happen here, never by hardcoding token values (see frontend/DESIGN.md).
const SEED = '#1A6B6B';

/**
 * Generates the Material Design 3 theme from the seed color and applies its
 * CSS custom properties to the document root.
 *
 * @param dark Whether to apply the dark color scheme.
 */
export function applyMd3Theme(dark: boolean): void {
  // themeFromSourceColor expands the seed into full MD3 tonal palettes with
  // light and dark schemes; applyTheme then writes the chosen scheme's
  // --md-sys-color-* custom properties onto <html>, where the --color-th-*
  // bridge variables in src/index.css pick them up.
  const theme = themeFromSourceColor(argbFromHex(SEED));
  applyTheme(theme, {
    target: document.documentElement,
    dark,
    // Emit plain --md-sys-color-* names only, not -light/-dark suffixed
    // variants; light/dark is chosen by re-running this with `dark` toggled.
    brightnessSuffix: false,
  });
}

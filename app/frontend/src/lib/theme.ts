import {
  applyTheme,
  argbFromHex,
  themeFromSourceColor,
} from '@material/material-color-utilities';

const SEED = '#1A6B6B';

/**
 * Generates the Material Design 3 theme from the seed color and applies its
 * CSS custom properties to the document root.
 *
 * @param dark Whether to apply the dark color scheme.
 */
export function applyMd3Theme(dark: boolean): void {
  const theme = themeFromSourceColor(argbFromHex(SEED));
  applyTheme(theme, {
    target: document.documentElement,
    dark,
    brightnessSuffix: false,
  });
}

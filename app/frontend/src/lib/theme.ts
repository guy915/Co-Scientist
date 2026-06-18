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

  // Remap primary → secondary so the app uses the muted sage-green accent
  // instead of the vibrant generated teal. applyTheme() writes concrete hex
  // values as inline custom properties; we overwrite primary with the
  // secondary values immediately after so every consumer sees the muted tone.
  const root = document.documentElement;
  const get = (v: string) => root.style.getPropertyValue(v);
  const set = (k: string, v: string) => root.style.setProperty(k, v);

  set('--md-sys-color-primary', get('--md-sys-color-secondary'));
  set('--md-sys-color-on-primary', get('--md-sys-color-on-secondary'));
  set('--md-sys-color-primary-container', get('--md-sys-color-secondary-container'));
  set('--md-sys-color-on-primary-container', get('--md-sys-color-on-secondary-container'));
  set('--md-sys-color-inverse-primary', get('--md-sys-color-secondary-container'));
}

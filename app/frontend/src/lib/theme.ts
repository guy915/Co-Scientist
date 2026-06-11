import { applyTheme, argbFromHex, themeFromSourceColor } from "@material/material-color-utilities";

const SEED = "#1A6B6B";

export function applyMd3Theme(dark: boolean): void {
  const theme = themeFromSourceColor(argbFromHex(SEED));
  applyTheme(theme, {
    target: document.documentElement,
    dark,
    brightnessSuffix: false,
  });
}

import {describe, it, expect, beforeEach} from 'vitest';
import {applyMd3Theme} from './theme';

function cssVar(name: string): string {
  return document.documentElement.style.getPropertyValue(name);
}

describe('applyMd3Theme', () => {
  beforeEach(() => document.documentElement.removeAttribute('style'));

  it('sets MD3 color custom properties on the document root', () => {
    applyMd3Theme(false);
    expect(cssVar('--md-sys-color-primary')).not.toBe('');
    expect(cssVar('--md-sys-color-surface')).not.toBe('');
    expect(cssVar('--md-sys-color-on-surface')).not.toBe('');
  });

  it('produces a different surface color in dark mode', () => {
    applyMd3Theme(false);
    const lightSurface = cssVar('--md-sys-color-surface');
    applyMd3Theme(true);
    const darkSurface = cssVar('--md-sys-color-surface');
    expect(lightSurface).not.toBe('');
    expect(darkSurface).not.toBe(lightSurface);
  });
});

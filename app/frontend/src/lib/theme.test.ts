/**
 * Copyright 2026 The Co-Scientist Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

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

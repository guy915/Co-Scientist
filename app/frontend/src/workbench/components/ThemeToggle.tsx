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

import '@material/web/iconbutton/icon-button.js';
import '@material/web/icon/icon.js';
import {useTheme} from '../ThemeContext';

export function ThemeToggle() {
  const {mode, toggle} = useTheme();
  const isDark = mode === 'dark';
  return (
    <md-icon-button
      onclick={toggle as EventListener}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {/* biome-ignore lint/a11y/noAriaHiddenOnFocusable: md-icon is a non-interactive decorative element */}
      <md-icon aria-hidden="true">
        {isDark ? 'dark_mode' : 'light_mode'}
      </md-icon>
    </md-icon-button>
  );
}
